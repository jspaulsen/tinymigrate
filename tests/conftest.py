from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def engine(database_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{database_path}")
    yield engine
    engine.dispose()
