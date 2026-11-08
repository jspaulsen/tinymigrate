import logging
import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import DBAPIError

from gander.errors import MigrationExecutionError, MigrationRollbackError, UnsupportedDialectError
from gander.migration import Migration, collect_migrations

logger = logging.getLogger(__name__)

# goose's default version table name, so a database goose migrated is picked up unchanged.
DEFAULT_TABLE = "goose_db_version"

# The SQLAlchemy dialect name of the only database the MVP supports.
_SUPPORTED_DIALECT = "sqlite"

# goose v3.28.0's sqlite3 version table DDL, whitespace included, so `sqlite_master` holds
# the same text whichever tool created the table. `{table}` goes in unquoted, as in goose.
_CREATE_VERSION_TABLE = """CREATE TABLE {table} (
\t\tid INTEGER PRIMARY KEY AUTOINCREMENT,
\t\tversion_id INTEGER NOT NULL,
\t\tis_applied INTEGER NOT NULL,
\t\ttstamp TIMESTAMP DEFAULT (datetime('now'))
\t)"""


def get_version(engine: Engine, *, table: str = DEFAULT_TABLE) -> int:
    """
    Return the current migration version of the database, or 0 for a fresh one.

    Creates the version table, with goose's seed row for version 0, when it does not exist.
    As in goose, a version whose newest row has `is_applied = 0` does not count as applied.
    Raises `UnsupportedDialectError` for a database other than SQLite.
    """
    with engine.connect() as connection:
        return _get_version(connection, table)


def migrate_up(engine: Engine, directory: Path, *, table: str = DEFAULT_TABLE) -> None:
    """
    Apply every migration in `directory` newer than the newest version in the version table.

    Each migration runs in its own transaction together with its version-table row, so a
    failing one leaves neither partial schema nor a row, and the ones before it stay
    applied. A `NO TRANSACTION` file runs statement by statement in autocommit. Raises
    `MigrationParseError` before touching the database when a file is malformed,
    `MigrationExecutionError` naming the file when the database rejects it, and
    `UnsupportedDialectError` for a database other than SQLite.
    """
    migrations = collect_migrations(directory)
    with engine.connect() as connection:
        _migrate_up(connection, migrations, table)


def migrate_down(engine: Engine, directory: Path, *, table: str = DEFAULT_TABLE) -> None:
    """
    Roll back the migration of the current version with its Down section.

    The current version is the one `get_version` returns. Its Down statements run in one
    transaction together with deleting every version-table row for it, so a failing one
    leaves the schema and the rows as they were; a `NO TRANSACTION` file runs statement by
    statement in autocommit. Raises `MigrationRollbackError` when the database is at version
    0, when `directory` has no file for the current version or that file has no Down
    section, `MigrationParseError` before touching the database when a file is malformed,
    `MigrationExecutionError` naming the file when the database rejects it, and
    `UnsupportedDialectError` for a database other than SQLite.
    """
    migrations = collect_migrations(directory)
    with engine.connect() as connection:
        _migrate_down(connection, migrations, directory, table)


def _get_version(connection: Connection, table: str) -> int:
    _prepare_connection(connection)
    with _begin_transaction(connection):
        _ensure_version_table(connection, table)
        return _read_version(connection, table)


def _migrate_up(connection: Connection, migrations: list[Migration], table: str) -> None:
    _prepare_connection(connection)
    with _begin_transaction(connection):
        _ensure_version_table(connection, table)
        # goose's `up` compares against the largest recorded version, applied or not.
        current = _read_max_version(connection, table)

    for migration in migrations:
        if migration.version <= current:
            continue
        _run_migration(connection, migration, migration.up_statements, lambda connection, version=migration.version: _insert_version(connection, table, version))
        logger.info("applied migration %s", migration.path.name)


def _migrate_down(connection: Connection, migrations: list[Migration], directory: Path, table: str) -> None:
    current = _get_version(connection, table)
    if current == 0:
        raise MigrationRollbackError(f"no migration to roll back: the database is at version 0 in {table}")
    migration = next((migration for migration in migrations if migration.version == current), None)
    if migration is None:
        raise MigrationRollbackError(f"no migration file for the current version {current} in {directory}")
    if migration.down_statements is None:
        raise MigrationRollbackError(f"{migration.path}: cannot roll back version {current}: the file has no -- +goose Down section")

    _run_migration(connection, migration, migration.down_statements, lambda connection: _delete_version(connection, table, current))
    logger.info("rolled back migration %s", migration.path.name)


def _prepare_connection(connection: Connection) -> None:
    if connection.dialect.name != _SUPPORTED_DIALECT:
        raise UnsupportedDialectError(f"gander supports only SQLite databases, not {connection.dialect.name!r}")
    # pysqlite's legacy mode opens a transaction only before DML, so DDL would autocommit; transactions
    # open with an explicit BEGIN instead. SQLAlchemy restores the isolation level on return to the pool.
    connection.execution_options(isolation_level="AUTOCOMMIT")


@contextmanager
def _begin_transaction(connection: Connection) -> Generator[None]:
    # SQLAlchemy's commit and rollback call the driver's, which end the open SQLite
    # transaction (or do nothing when SQLite already rolled it back).
    with connection.begin():
        connection.exec_driver_sql("BEGIN")
        yield


def _run_migration(connection: Connection, migration: Migration, statements: tuple[str, ...], record_version: Callable[[Connection], None]) -> None:
    try:
        with _begin_transaction(connection) if migration.use_transaction else connection.begin():
            for statement in statements:
                for sql in _split_statement(statement):
                    try:
                        connection.exec_driver_sql(sql)
                    except DBAPIError as error:
                        raise MigrationExecutionError(f"{migration.path}: statement failed: {error.orig}\n{sql}") from error
            record_version(connection)
    except DBAPIError as error:
        raise MigrationExecutionError(f"{migration.path}: failed to update the version table for version {migration.version} or commit: {error.orig}") from error


def _split_statement(statement: str) -> list[str]:
    # goose's splitter can leave several SQL statements in one string (`a; b;`), which Python's sqlite3
    # refuses; SQLite's completeness check splits them without breaking a literal, comment or trigger.
    sql_statements: list[str] = []
    pending = ""
    *parts, remainder = statement.split(";")
    for part in parts:
        pending += part + ";"
        if sqlite3.complete_statement(pending):
            sql_statements.append(pending.strip())
            pending = ""
    pending += remainder
    if not all(line.lstrip().startswith("--") for line in pending.splitlines() if line.strip()):
        sql_statements.append(pending.strip())

    return sql_statements


def _ensure_version_table(connection: Connection, table: str) -> None:
    if inspect(connection).has_table(table):
        return
    connection.exec_driver_sql(_CREATE_VERSION_TABLE.format(table=table))
    _insert_version(connection, table, 0)


def _insert_version(connection: Connection, table: str, version: int) -> None:
    connection.execute(text(f"INSERT INTO {table} (version_id, is_applied) VALUES (:version, 1)"), {"version": version})


def _delete_version(connection: Connection, table: str, version: int) -> None:
    # As goose does, every row for the version goes, not only the newest.
    connection.execute(text(f"DELETE FROM {table} WHERE version_id = :version"), {"version": version})


def _read_version(connection: Connection, table: str) -> int:
    # goose's rule: walking rows newest first, the first version whose newest row is applied.
    rows = connection.execute(text(f"SELECT version_id, is_applied FROM {table} ORDER BY id DESC"))
    not_applied: set[int] = set()
    for version, is_applied in rows:
        if version in not_applied:
            continue
        if is_applied:
            return version
        not_applied.add(version)

    return 0


def _read_max_version(connection: Connection, table: str) -> int:
    return connection.execute(text(f"SELECT MAX(version_id) FROM {table}")).scalar_one() or 0
