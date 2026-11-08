import asyncio
import shutil
import sqlite3
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.dialects import registry
from sqlalchemy.dialects.sqlite.pysqlite import SQLiteDialect_pysqlite
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import tinymigrate
from tinymigrate import (
    MigrationExecutionError,
    MigrationParseError,
    MigrationRollbackError,
    TinymigrateError,
    TransactionStateError,
    UnsupportedDialectError,
    get_version,
    get_version_async,
    migrate_down,
    migrate_down_async,
    migrate_up,
    migrate_up_async,
)

# The real migration directories of two small SQLModel apps, converted to tinymigrate syntax.
FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures"
CHAT_APP_DIRECTORY = FIXTURE_DIRECTORY / "chat_app"
PERSONA_APP_DIRECTORY = FIXTURE_DIRECTORY / "persona_app"

# The newest version in each fixture directory.
CHAT_APP_LATEST_VERSION = 7
PERSONA_APP_LATEST_VERSION = 4

# The version table name tinymigrate defaults to.
VERSION_TABLE = "tinymigrate_migration"

# `PRAGMA table_info` of the version table: (name, type, notnull, default, primary key position).
VERSION_TABLE_COLUMNS = [("version", "INTEGER", 0, None, 1), ("applied_at", "TEXT", 1, None, 0)]


class _OtherDialect(SQLiteDialect_pysqlite):
    """
    A pysqlite dialect under another name, standing in for a database tinymigrate does not support.
    """

    name = "otherdb"


registry.register("otherdb", __name__, "_OtherDialect")


def _write_migration(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")

    return path


def _read_versions(database: Path, table: str = VERSION_TABLE) -> list[int]:
    with sqlite3.connect(database) as connection:
        return [version for (version,) in connection.execute(f"SELECT version FROM {table} ORDER BY version")]


def _read_schema(database: Path) -> list[tuple[str, str, str, str | None]]:
    with sqlite3.connect(database) as connection:
        return connection.execute("SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name != ? ORDER BY type, name", (VERSION_TABLE,)).fetchall()


def _read_table_names(database: Path) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {name for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _copy_first_migrations(source: Path, destination: Path, count: int) -> Path:
    destination.mkdir()
    for path in sorted(source.glob("*.sql"))[:count]:
        shutil.copy(path, destination / path.name)

    return destination


def test_the_runner_names_are_importable_from_the_package_root() -> None:
    assert {"get_version", "migrate_up", "migrate_down", "MigrationExecutionError", "MigrationRollbackError", "UnsupportedDialectError"} <= set(tinymigrate.__all__)
    assert issubclass(MigrationExecutionError, TinymigrateError)
    assert issubclass(MigrationRollbackError, TinymigrateError)
    assert issubclass(UnsupportedDialectError, TinymigrateError)


def test_a_fresh_database_is_at_version_zero_with_an_empty_version_table(engine: Engine, database_path: Path) -> None:
    assert get_version(engine) == 0
    assert _read_versions(database_path) == []


def test_the_version_table_has_a_version_key_and_an_applied_at_column(engine: Engine, database_path: Path) -> None:
    get_version(engine)

    with sqlite3.connect(database_path) as connection:
        assert [tuple(column[1:]) for column in connection.execute(f"PRAGMA table_info({VERSION_TABLE})")] == VERSION_TABLE_COLUMNS


def test_each_applied_version_records_when_it_was_applied_in_utc(engine: Engine, database_path: Path) -> None:
    before = datetime.now(UTC)
    migrate_up(engine, PERSONA_APP_DIRECTORY)
    after = datetime.now(UTC)

    with sqlite3.connect(database_path) as connection:
        applied_at = [datetime.fromisoformat(value) for (value,) in connection.execute(f"SELECT applied_at FROM {VERSION_TABLE} ORDER BY version")]
    assert len(applied_at) == PERSONA_APP_LATEST_VERSION
    assert all(value.utcoffset() == UTC.utcoffset(None) and before <= value <= after for value in applied_at)


def test_the_version_table_name_is_a_parameter(engine: Engine, database_path: Path) -> None:
    migrate_up(engine, PERSONA_APP_DIRECTORY, table="schema_version")

    assert get_version(engine, table="schema_version") == PERSONA_APP_LATEST_VERSION
    assert VERSION_TABLE not in _read_table_names(database_path)


def test_migrate_down_uses_the_version_table_name_it_is_given(engine: Engine, database_path: Path) -> None:
    migrate_up(engine, PERSONA_APP_DIRECTORY, table="schema_version")

    migrate_down(engine, PERSONA_APP_DIRECTORY, table="schema_version")

    assert get_version(engine, table="schema_version") == PERSONA_APP_LATEST_VERSION - 1
    assert _read_versions(database_path, "schema_version") == [1, 2, 3]
    assert VERSION_TABLE not in _read_table_names(database_path)


def test_migrate_up_applies_every_migration_and_records_each_version(engine: Engine, database_path: Path) -> None:
    migrate_up(engine, PERSONA_APP_DIRECTORY)

    assert get_version(engine) == PERSONA_APP_LATEST_VERSION
    assert _read_versions(database_path) == [1, 2, 3, 4]
    assert {"personas", "conversations", "messages"} <= _read_table_names(database_path)


def test_migrate_up_on_an_up_to_date_database_does_nothing(engine: Engine, database_path: Path) -> None:
    migrate_up(engine, CHAT_APP_DIRECTORY)
    schema = _read_schema(database_path)
    rows = _read_versions(database_path)

    migrate_up(engine, CHAT_APP_DIRECTORY)

    assert _read_schema(database_path) == schema
    assert _read_versions(database_path) == rows


def test_migrate_up_applies_only_migrations_newer_than_the_current_version(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    migrate_up(engine, _copy_first_migrations(PERSONA_APP_DIRECTORY, tmp_path / "partial", 2))

    migrate_up(engine, PERSONA_APP_DIRECTORY)

    assert _read_versions(database_path) == [1, 2, 3, 4]


def test_a_failing_statement_rolls_back_its_migration_only(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_a.sql", "-- up\nCREATE TABLE a (x INTEGER);\n")
    _write_migration(directory, "00002_b.sql", "-- up\nCREATE TABLE b (x INTEGER);\nINSERT INTO missing VALUES (1);\n")

    with pytest.raises(MigrationExecutionError, match=r"00002_b\.sql: .*no such table: missing") as raised:
        migrate_up(engine, directory)

    assert isinstance(raised.value.__cause__, DBAPIError)
    assert "INSERT INTO missing VALUES (1);" in str(raised.value)
    assert _read_table_names(database_path) == {VERSION_TABLE, "a"}
    assert _read_versions(database_path) == [1]


def test_a_failing_no_transaction_migration_keeps_its_earlier_statements_and_records_no_version(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_a.sql", "-- no transaction\n-- up\nCREATE TABLE a (x INTEGER);\nINSERT INTO missing VALUES (1);\n")

    with pytest.raises(MigrationExecutionError, match=r"00001_a\.sql: "):
        migrate_up(engine, directory)

    assert "a" in _read_table_names(database_path)
    assert _read_versions(database_path) == []


def test_a_failing_no_transaction_migration_keeps_rows_its_earlier_statements_inserted(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_a.sql", "-- up\nCREATE TABLE a (x INTEGER);\n")
    _write_migration(directory, "00002_b.sql", "-- no transaction\n-- up\nINSERT INTO a VALUES (1);\nINSERT INTO missing VALUES (1);\n")

    with pytest.raises(MigrationExecutionError, match=r"00002_b\.sql: "):
        migrate_up(engine, directory)

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT x FROM a").fetchall() == [(1,)]
    assert _read_versions(database_path) == [1]


def test_a_no_transaction_migration_can_run_a_statement_sqlite_refuses_in_a_transaction(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_vacuum.sql", "-- no transaction\n-- up\nVACUUM;\n")

    migrate_up(engine, directory)

    assert _read_versions(database_path) == [1]


def test_a_transactional_migration_runs_inside_a_transaction(engine: Engine, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_vacuum.sql", "-- up\nVACUUM;\n")

    with pytest.raises(MigrationExecutionError, match="cannot VACUUM from within a transaction"):
        migrate_up(engine, directory)


def test_a_parsed_statement_holding_several_sql_statements_runs_them_all(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_x.sql", "-- up\nCREATE TABLE a (x INTEGER); CREATE TABLE b (\n    x INTEGER\n);\n")

    migrate_up(engine, directory)

    assert {"a", "b"} <= _read_table_names(database_path)


def test_a_failure_in_the_second_of_two_sql_statements_rolls_back_the_first(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_x.sql", "-- up\nCREATE TABLE a (x INTEGER); INSERT INTO missing VALUES (1);\n")

    with pytest.raises(MigrationExecutionError, match="no such table: missing"):
        migrate_up(engine, directory)

    assert "a" not in _read_table_names(database_path)


def test_a_trigger_body_with_semicolons_runs_as_one_statement(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    trigger = "CREATE TRIGGER t AFTER INSERT ON a BEGIN\n    INSERT INTO b VALUES (new.x);\n    INSERT INTO b VALUES (new.x);\nEND;\n"
    tables = "CREATE TABLE a (x INTEGER);\nCREATE TABLE b (x INTEGER);\n"
    migration_text = f"-- up\n{tables}{trigger}INSERT INTO a VALUES (1);\n"
    _write_migration(directory, "00001_x.sql", migration_text)

    migrate_up(engine, directory)

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT count(*) FROM b").fetchone() == (2,)


def test_a_colon_name_inside_a_string_literal_is_not_a_bind_parameter(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_x.sql", "-- up\nCREATE TABLE a (x TEXT);\nINSERT INTO a VALUES (':name %s %(x)s');\n")

    migrate_up(engine, directory)

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT x FROM a").fetchone() == (":name %s %(x)s",)


def test_a_trailing_comment_after_the_last_statement_is_harmless(engine: Engine, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_x.sql", "-- up\nCREATE TABLE a (x INTEGER); -- note\n")

    migrate_up(engine, directory)

    assert get_version(engine) == 1


def test_both_fixture_directories_apply_on_an_engine_with_an_apps_connect_pragmas(tmp_path: Path) -> None:
    for directory, latest in [(CHAT_APP_DIRECTORY, CHAT_APP_LATEST_VERSION), (PERSONA_APP_DIRECTORY, PERSONA_APP_LATEST_VERSION)]:
        engine = create_engine(f"sqlite:///{tmp_path / directory.name}.db")

        @event.listens_for(engine, "connect")
        def _set_pragmas(dbapi_connection: sqlite3.Connection, _connection_record: object) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        try:
            migrate_up(engine, directory)
            assert get_version(engine) == latest
            with engine.connect() as connection:
                assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        finally:
            engine.dispose()


def test_the_engine_still_runs_its_own_statements_in_transactions_afterwards(engine: Engine, database_path: Path) -> None:
    migrate_up(engine, PERSONA_APP_DIRECTORY)

    with engine.connect() as connection:
        connection.execute(text("INSERT INTO personas (name, prompt) VALUES ('x', 'y')"))
        connection.rollback()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT count(*) FROM personas").fetchone() == (1,)


def test_a_database_other_than_sqlite_raises(tmp_path: Path) -> None:
    engine = create_engine(f"otherdb:///{tmp_path / 'other.db'}")
    try:
        with pytest.raises(UnsupportedDialectError, match="'otherdb'"):
            migrate_up(engine, PERSONA_APP_DIRECTORY)
        with pytest.raises(UnsupportedDialectError, match="'otherdb'"):
            get_version(engine)
    finally:
        engine.dispose()


def test_a_failing_commit_rolls_back_its_migration(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    migration_text = "-- up\nPRAGMA defer_foreign_keys = ON;\nCREATE TABLE a (x INTEGER REFERENCES a (y), y INTEGER UNIQUE);\nINSERT INTO a VALUES (1, NULL);\n"
    _write_migration(directory, "00001_x.sql", migration_text)
    event.listen(engine, "connect", lambda dbapi_connection, _record: dbapi_connection.execute("PRAGMA foreign_keys=ON"))

    with pytest.raises(MigrationExecutionError, match=r"00001_x\.sql: failed to update the version table for version 1 or commit: FOREIGN KEY constraint failed"):
        migrate_up(engine, directory)

    assert "a" not in _read_table_names(database_path)
    assert _read_versions(database_path) == []


def test_a_missing_migration_older_than_the_largest_version_is_skipped(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_a.sql", "-- up\nCREATE TABLE a (x INTEGER);\n")
    _write_migration(directory, "00003_c.sql", "-- up\nCREATE TABLE c (x INTEGER);\n")
    migrate_up(engine, directory)
    _write_migration(directory, "00002_b.sql", "-- up\nCREATE TABLE b (x INTEGER);\n")

    migrate_up(engine, directory)

    assert "b" not in _read_table_names(database_path)
    assert _read_versions(database_path) == [1, 3]


def test_migrate_down_rolls_back_the_newest_migration_and_deletes_its_row(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    partial_database = tmp_path / "partial.db"
    partial_engine = create_engine(f"sqlite:///{partial_database}")
    try:
        migrate_up(partial_engine, _copy_first_migrations(PERSONA_APP_DIRECTORY, tmp_path / "partial", PERSONA_APP_LATEST_VERSION - 1))
    finally:
        partial_engine.dispose()
    migrate_up(engine, PERSONA_APP_DIRECTORY)

    migrate_down(engine, PERSONA_APP_DIRECTORY)

    assert get_version(engine) == PERSONA_APP_LATEST_VERSION - 1
    assert _read_schema(database_path) == _read_schema(partial_database)
    assert _read_versions(database_path) == [1, 2, 3]


def test_migrate_down_on_a_fresh_database_raises(engine: Engine, database_path: Path) -> None:
    with pytest.raises(MigrationRollbackError, match="no migration to roll back"):
        migrate_down(engine, PERSONA_APP_DIRECTORY)

    assert _read_versions(database_path) == []


def test_migrate_down_raises_when_the_current_versions_file_is_missing(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    migrate_up(engine, PERSONA_APP_DIRECTORY)
    schema = _read_schema(database_path)

    with pytest.raises(MigrationRollbackError, match=f"no migration file for the current version {PERSONA_APP_LATEST_VERSION} in"):
        migrate_down(engine, _copy_first_migrations(PERSONA_APP_DIRECTORY, tmp_path / "partial", 2))

    assert _read_schema(database_path) == schema
    assert get_version(engine) == PERSONA_APP_LATEST_VERSION


def test_migrate_down_raises_for_a_migration_without_a_down_section(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_a.sql", "-- up\nCREATE TABLE a (x INTEGER);\n")
    migrate_up(engine, directory)

    with pytest.raises(MigrationRollbackError, match=r"00001_a\.sql: .*no -- down section"):
        migrate_down(engine, directory)

    assert "a" in _read_table_names(database_path)
    assert _read_versions(database_path) == [1]


def test_migrate_down_with_an_empty_down_section_only_deletes_the_row(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_a.sql", "-- up\nCREATE TABLE a (x INTEGER);\n-- down\n")
    migrate_up(engine, directory)

    migrate_down(engine, directory)

    assert "a" in _read_table_names(database_path)
    assert _read_versions(database_path) == []


def test_a_failing_down_leaves_the_schema_and_version_row_intact(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_a.sql", "-- up\nCREATE TABLE a (x INTEGER);\n-- down\nDROP TABLE a;\nINSERT INTO missing VALUES (1);\n")
    migrate_up(engine, directory)
    schema = _read_schema(database_path)

    with pytest.raises(MigrationExecutionError, match=r"00001_a\.sql: .*no such table: missing"):
        migrate_down(engine, directory)

    assert _read_schema(database_path) == schema
    assert _read_versions(database_path) == [1]


def test_a_no_transaction_down_runs_in_autocommit(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_vacuum.sql", "-- no transaction\n-- up\nVACUUM;\n-- down\nVACUUM;\n")
    migrate_up(engine, directory)

    migrate_down(engine, directory)

    assert _read_versions(database_path) == []


def test_a_transactional_down_runs_inside_a_transaction(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_vacuum.sql", "-- up\nSELECT 1;\n-- down\nVACUUM;\n")
    migrate_up(engine, directory)

    with pytest.raises(MigrationExecutionError, match="cannot VACUUM from within a transaction"):
        migrate_down(engine, directory)

    assert _read_versions(database_path) == [1]


@pytest.mark.parametrize(
    ("directory", "latest"), [(CHAT_APP_DIRECTORY, CHAT_APP_LATEST_VERSION), (PERSONA_APP_DIRECTORY, PERSONA_APP_LATEST_VERSION)], ids=["chat_app", "persona_app"]
)
def test_rolling_every_migration_back_and_reapplying_gives_the_same_schema(engine: Engine, database_path: Path, directory: Path, latest: int) -> None:
    migrate_up(engine, directory)
    schema = _read_schema(database_path)

    for _ in range(latest):
        migrate_down(engine, directory)
    assert get_version(engine) == 0
    assert _read_table_names(database_path) == {VERSION_TABLE, "sqlite_sequence"}
    migrate_up(engine, directory)

    assert _read_schema(database_path) == schema
    assert get_version(engine) == latest


def test_migrate_up_and_migrate_down_accept_a_str_directory(engine: Engine) -> None:
    migrate_up(engine, str(PERSONA_APP_DIRECTORY))
    assert get_version(engine) == PERSONA_APP_LATEST_VERSION

    migrate_down(engine, str(PERSONA_APP_DIRECTORY))
    assert get_version(engine) == PERSONA_APP_LATEST_VERSION - 1


@pytest.mark.parametrize("migrate", [migrate_up, migrate_down], ids=["up", "down"])
def test_a_directory_with_no_migration_files_raises_without_touching_the_database(
    engine: Engine, database_path: Path, tmp_path: Path, migrate: Callable[[Engine, Path], None]
) -> None:
    empty_directory = tmp_path / "empty"
    empty_directory.mkdir()

    with pytest.raises(MigrationParseError, match="no migration files found in .*empty"):
        migrate(engine, empty_directory)

    assert not database_path.exists()


@pytest.mark.parametrize("migrate", [migrate_up, migrate_down], ids=["up", "down"])
def test_a_missing_directory_raises_without_touching_the_database(engine: Engine, database_path: Path, tmp_path: Path, migrate: Callable[[Engine, Path], None]) -> None:
    with pytest.raises(MigrationParseError, match="migration directory .*nope does not exist"):
        migrate(engine, tmp_path / "nope")

    assert not database_path.exists()


def test_a_failing_no_transaction_down_keeps_its_earlier_statements_and_the_version_row(engine: Engine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    down = "-- down\nDROP TABLE a;\nINSERT INTO missing VALUES (1);\nDROP TABLE b;\n"
    migration_text = f"-- no transaction\n-- up\nCREATE TABLE a (x INTEGER);\nCREATE TABLE b (x INTEGER);\n{down}"
    _write_migration(directory, "00001_ab.sql", migration_text)
    migrate_up(engine, directory)

    with pytest.raises(MigrationExecutionError, match=r"00001_ab\.sql: .*no such table: missing"):
        migrate_down(engine, directory)

    assert "a" not in _read_table_names(database_path)
    assert "b" in _read_table_names(database_path)
    assert _read_versions(database_path) == [1]


def _begin_on_connect(connection: Connection) -> None:
    connection.exec_driver_sql("SELECT 1")


def test_a_connection_that_already_began_a_transaction_raises(engine: Engine, database_path: Path) -> None:
    event.listen(engine, "engine_connect", _begin_on_connect)

    with pytest.raises(TransactionStateError, match="already has a transaction begun"):
        get_version(engine)
    with pytest.raises(TransactionStateError, match="already has a transaction begun"):
        migrate_up(engine, PERSONA_APP_DIRECTORY)
    with pytest.raises(TransactionStateError, match="already has a transaction begun"):
        migrate_down(engine, PERSONA_APP_DIRECTORY)

    assert _read_table_names(database_path) == set()


async def test_get_version_async_reads_a_fresh_database_as_version_zero(async_engine: AsyncEngine, database_path: Path) -> None:
    assert await get_version_async(async_engine) == 0
    assert _read_versions(database_path) == []


@pytest.mark.parametrize(
    ("directory", "latest"), [(CHAT_APP_DIRECTORY, CHAT_APP_LATEST_VERSION), (PERSONA_APP_DIRECTORY, PERSONA_APP_LATEST_VERSION)], ids=["chat_app", "persona_app"]
)
async def test_the_async_functions_build_and_roll_back_the_same_schema_as_the_sync_ones(
    async_engine: AsyncEngine, database_path: Path, tmp_path: Path, directory: Path, latest: int
) -> None:
    sync_database = tmp_path / "sync.db"
    sync_engine = create_engine(f"sqlite:///{sync_database}")
    try:
        migrate_up(sync_engine, directory)
    finally:
        sync_engine.dispose()

    await migrate_up_async(async_engine, directory)

    assert await get_version_async(async_engine) == latest
    assert _read_schema(database_path) == _read_schema(sync_database)
    assert _read_versions(database_path) == _read_versions(sync_database)

    for _ in range(latest):
        await migrate_down_async(async_engine, directory)
    assert await get_version_async(async_engine) == 0
    assert _read_table_names(database_path) == {VERSION_TABLE, "sqlite_sequence"}


async def test_the_async_functions_use_the_version_table_name_they_are_given(async_engine: AsyncEngine, database_path: Path) -> None:
    await migrate_up_async(async_engine, PERSONA_APP_DIRECTORY, table="schema_version")
    await migrate_down_async(async_engine, PERSONA_APP_DIRECTORY, table="schema_version")

    assert await get_version_async(async_engine, table="schema_version") == PERSONA_APP_LATEST_VERSION - 1
    assert VERSION_TABLE not in _read_table_names(database_path)


async def test_a_failure_in_the_second_statement_over_aiosqlite_leaves_no_partial_schema_or_version_row(async_engine: AsyncEngine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_a.sql", "-- up\nCREATE TABLE a (x INTEGER);\nINSERT INTO missing VALUES (1);\n")

    with pytest.raises(MigrationExecutionError, match=r"00001_a\.sql: .*no such table: missing") as raised:
        await migrate_up_async(async_engine, directory)

    assert isinstance(raised.value.__cause__, DBAPIError)
    assert _read_table_names(database_path) == {VERSION_TABLE}
    assert _read_versions(database_path) == []


async def test_a_failing_down_over_aiosqlite_leaves_the_schema_and_version_row_intact(async_engine: AsyncEngine, database_path: Path, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_a.sql", "-- up\nCREATE TABLE a (x INTEGER);\n-- down\nDROP TABLE a;\nINSERT INTO missing VALUES (1);\n")
    await migrate_up_async(async_engine, directory)

    with pytest.raises(MigrationExecutionError, match="no such table: missing"):
        await migrate_down_async(async_engine, directory)

    assert "a" in _read_table_names(database_path)
    assert _read_versions(database_path) == [1]


async def test_a_transactional_migration_over_aiosqlite_runs_inside_a_transaction(async_engine: AsyncEngine, tmp_path: Path) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_vacuum.sql", "-- up\nVACUUM;\n")

    with pytest.raises(MigrationExecutionError, match="cannot VACUUM from within a transaction"):
        await migrate_up_async(async_engine, directory)


async def test_a_no_transaction_migration_over_aiosqlite_runs_in_autocommit_and_keeps_what_ran_before_a_failure(
    async_engine: AsyncEngine, database_path: Path, tmp_path: Path
) -> None:
    directory = tmp_path / "migrations"
    _write_migration(directory, "00001_vacuum.sql", "-- no transaction\n-- up\nVACUUM;\n")
    _write_migration(directory, "00002_a.sql", "-- up\nCREATE TABLE a (x INTEGER);\n")
    _write_migration(directory, "00003_b.sql", "-- no transaction\n-- up\nINSERT INTO a VALUES (1);\nINSERT INTO missing VALUES (1);\n")

    with pytest.raises(MigrationExecutionError, match=r"00003_b\.sql: "):
        await migrate_up_async(async_engine, directory)

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT x FROM a").fetchall() == [(1,)]
    assert _read_versions(database_path) == [1, 2]


async def test_an_async_connection_that_already_began_a_transaction_raises(async_engine: AsyncEngine, database_path: Path) -> None:
    event.listen(async_engine.sync_engine, "engine_connect", _begin_on_connect)

    with pytest.raises(TransactionStateError, match="already has a transaction begun"):
        await get_version_async(async_engine)
    with pytest.raises(TransactionStateError, match="already has a transaction begun"):
        await migrate_up_async(async_engine, PERSONA_APP_DIRECTORY)
    with pytest.raises(TransactionStateError, match="already has a transaction begun"):
        await migrate_down_async(async_engine, PERSONA_APP_DIRECTORY)

    assert _read_table_names(database_path) == set()


class Character(SQLModel, table=True):
    """
    A row of the chat app's `characters` table, mapped onto the columns its first migration creates.
    """

    __tablename__ = "characters"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    description: str
    first_message: str
    created_at: str


class Chat(SQLModel, table=True):
    """
    A row of the chat app's `chats` table, whose `character_id` references `characters`.
    """

    __tablename__ = "chats"

    id: int | None = Field(default=None, primary_key=True)
    character_id: int = Field(foreign_key="characters.id")
    created_at: str


async def test_a_sqlmodel_async_session_reads_and_writes_a_table_the_async_migrations_built(async_engine: AsyncEngine) -> None:
    await migrate_up_async(async_engine, CHAT_APP_DIRECTORY)
    sessions = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async with sessions() as session:
        session.add(Character(name="Mira", description="a cartographer", first_message="Hello.", created_at="2026-01-01T00:00:00Z"))
        await session.commit()
    async with sessions() as session:
        characters = [(character.name, character.first_message) for character in (await session.exec(select(Character))).all()]
        session.add(Chat(character_id=999, created_at="2026-01-01T00:00:00Z"))
        with pytest.raises(IntegrityError, match="FOREIGN KEY constraint failed"):
            await session.commit()

    assert characters == [("Mira", "Hello.")]
    assert await get_version_async(async_engine) == CHAT_APP_LATEST_VERSION


async def test_the_async_functions_accept_a_str_directory(async_engine: AsyncEngine) -> None:
    await migrate_up_async(async_engine, str(PERSONA_APP_DIRECTORY))
    assert await get_version_async(async_engine) == PERSONA_APP_LATEST_VERSION

    await migrate_down_async(async_engine, str(PERSONA_APP_DIRECTORY))
    assert await get_version_async(async_engine) == PERSONA_APP_LATEST_VERSION - 1


@pytest.mark.parametrize("migrate", [migrate_up_async, migrate_down_async], ids=["up", "down"])
async def test_an_async_migration_on_a_directory_with_no_migration_files_raises_without_touching_the_database(
    async_engine: AsyncEngine, database_path: Path, tmp_path: Path, migrate: Callable[[AsyncEngine, Path], Awaitable[None]]
) -> None:
    empty_directory = tmp_path / "empty"
    empty_directory.mkdir()

    with pytest.raises(MigrationParseError, match="no migration files found in .*empty"):
        await migrate(async_engine, empty_directory)

    assert not await asyncio.to_thread(database_path.exists)
