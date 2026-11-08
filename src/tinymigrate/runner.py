import logging
import sqlite3
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from tinymigrate.errors import MigrationExecutionError, MigrationRollbackError, TransactionStateError, UnsupportedDialectError
from tinymigrate.migration import Migration, collect_migrations

logger = logging.getLogger(__name__)

# The version table's name when the caller passes none.
DEFAULT_TABLE = "tinymigrate_migration"

# The SQLAlchemy dialect name of the only database the MVP supports.
_SUPPORTED_DIALECT = "sqlite"

# One row per applied migration; `{table}` goes in unquoted, so it must be a plain identifier.
_CREATE_VERSION_TABLE = "CREATE TABLE IF NOT EXISTS {table} (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"


def get_version(engine: Engine, *, table: str = DEFAULT_TABLE) -> int:
    """
    Return the newest applied migration version of the database, or 0 for a fresh one.

    Creates the version table when it does not exist. Raises `UnsupportedDialectError` for
    a database other than SQLite, and `TransactionStateError` when the checked-out
    connection already has a transaction begun.
    """
    with engine.connect() as connection:
        return _get_version(connection, table)


def migrate_up(engine: Engine, directory: str | Path, *, table: str = DEFAULT_TABLE) -> None:
    """
    Apply every migration in `directory` newer than the newest version in the version table.

    Each migration runs in its own transaction together with inserting its version-table
    row, stamped with the UTC time in ISO-8601, so a failing one leaves neither partial
    schema nor a row, and the ones before it stay applied. A `-- no transaction` file runs
    statement by statement in autocommit. Raises
    `MigrationParseError` before touching the database when a file is malformed or
    `directory` has no `.sql` file, `MigrationExecutionError` naming the file when the
    database rejects it, `UnsupportedDialectError` for a database other than SQLite, and
    `TransactionStateError` when the checked-out connection already has a transaction begun.
    """
    migrations = collect_migrations(directory)
    with engine.connect() as connection:
        _migrate_up(connection, migrations, table)


def migrate_down(engine: Engine, directory: str | Path, *, table: str = DEFAULT_TABLE) -> None:
    """
    Roll back the migration of the current version with its Down section.

    The current version is the one `get_version` returns, and as there the version table is
    created when it does not exist, even when the rollback then raises. Its Down statements
    run in one transaction together with deleting its version-table row, so a failing one
    leaves the schema and the row as they were; a `-- no transaction` file runs statement
    by statement in autocommit. Raises `MigrationRollbackError` when the database
    is at version 0, when `directory` has no file for the current version or that file has
    no Down section, `MigrationParseError` before touching the database when any file in
    `directory` is malformed or there is none, `MigrationExecutionError` naming the file
    when the database rejects it, `UnsupportedDialectError` for a database other than
    SQLite, and `TransactionStateError` when the checked-out connection already has a
    transaction begun.
    """
    migrations = collect_migrations(directory)
    with engine.connect() as connection:
        _migrate_down(connection, migrations, directory, table)


async def get_version_async(engine: AsyncEngine, *, table: str = DEFAULT_TABLE) -> int:
    """
    Return the current migration version of the database behind an `AsyncEngine`, or 0 for a fresh one.

    Behaves as `get_version`, running it on one of the engine's connections.
    """
    async with engine.connect() as connection:
        return await connection.run_sync(_get_version, table)


async def migrate_up_async(engine: AsyncEngine, directory: str | Path, *, table: str = DEFAULT_TABLE) -> None:
    """
    Apply every migration in `directory` newer than the newest version, over an `AsyncEngine`.

    Behaves as `migrate_up`, transactions and errors included, running it on one of the
    engine's connections.
    """
    migrations = collect_migrations(directory)
    async with engine.connect() as connection:
        await connection.run_sync(_migrate_up, migrations, table)


async def migrate_down_async(engine: AsyncEngine, directory: str | Path, *, table: str = DEFAULT_TABLE) -> None:
    """
    Roll back the migration of the current version with its Down section, over an `AsyncEngine`.

    Behaves as `migrate_down`, transactions and errors included, running it on one of the
    engine's connections.
    """
    migrations = collect_migrations(directory)
    async with engine.connect() as connection:
        await connection.run_sync(_migrate_down, migrations, directory, table)


def _get_version(connection: Connection, table: str) -> int:
    _prepare_connection(connection)
    with _begin_transaction(connection):
        connection.exec_driver_sql(_CREATE_VERSION_TABLE.format(table=table))
        return connection.execute(text(f"SELECT MAX(version) FROM {table}")).scalar_one() or 0


def _migrate_up(connection: Connection, migrations: list[Migration], table: str) -> None:
    current = _get_version(connection, table)
    for migration in migrations:
        if migration.version <= current:
            continue
        _run_migration(connection, migration, migration.up_statements, lambda connection, version=migration.version: _insert_version(connection, table, version))
        logger.info("applied migration %s", migration.path.name)


def _migrate_down(connection: Connection, migrations: list[Migration], directory: str | Path, table: str) -> None:
    current = _get_version(connection, table)
    if current == 0:
        raise MigrationRollbackError(f"no migration to roll back: the database is at version 0 in {table}")
    migration = next((migration for migration in migrations if migration.version == current), None)
    if migration is None:
        raise MigrationRollbackError(f"no migration file for the current version {current} in {directory}")
    if migration.down_statements is None:
        raise MigrationRollbackError(f"{migration.path}: cannot roll back version {current}: the file has no -- down section")

    _run_migration(connection, migration, migration.down_statements, lambda connection: _delete_version(connection, table, current))
    logger.info("rolled back migration %s", migration.path.name)


def _prepare_connection(connection: Connection) -> None:
    if connection.dialect.name != _SUPPORTED_DIALECT:
        raise UnsupportedDialectError(f"tinymigrate supports only SQLite databases, not {connection.dialect.name!r}")
    if connection.in_transaction():
        raise TransactionStateError(
            "the connection already has a transaction begun (did an engine_connect listener run a statement?); tinymigrate switches it to autocommit, so it needs one with none"
        )
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
    # A parsed statement ends at the end of a line, so it can hold several (`a; b;`), which Python's sqlite3
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


def _insert_version(connection: Connection, table: str, version: int) -> None:
    connection.execute(text(f"INSERT INTO {table} (version, applied_at) VALUES (:version, :applied_at)"), {"version": version, "applied_at": datetime.now(UTC).isoformat()})


def _delete_version(connection: Connection, table: str, version: int) -> None:
    connection.execute(text(f"DELETE FROM {table} WHERE version = :version"), {"version": version})
