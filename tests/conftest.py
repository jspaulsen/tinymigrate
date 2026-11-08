from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import ConnectionPoolEntry


def _set_hearth_pragmas(dbapi_connection: DBAPIConnection, _connection_record: ConnectionPoolEntry) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def engine(database_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{database_path}")
    yield engine
    engine.dispose()


@pytest.fixture
async def async_engine(database_path: Path) -> AsyncIterator[AsyncEngine]:
    """
    Yield an aiosqlite engine set up as hearth's `Database` sets up its own.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    event.listen(engine.sync_engine, "connect", _set_hearth_pragmas)
    yield engine
    await engine.dispose()
