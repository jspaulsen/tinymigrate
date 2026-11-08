# gander

Apply [goose](https://github.com/pressly/goose)-compatible SQL migration files through
SQLAlchemy, without the goose binary.

gander is plain Python on top of SQLAlchemy 2.x, so it works with SQLModel apps, sync or
async. It reads the same migration files goose does and keeps goose's `goose_db_version`
table, so a database goose migrated is continued by gander and the reverse. There is no
subprocess, no `GOOSE_*` environment variable and no `.env` lookup: the engine, the
directory and the table name are all passed explicitly.

SQLite only, for now. No CLI, no `create` command, no Go migrations, no `ENVSUB`, no
out-of-order migrations, no locking ([`docs/FUTURE.md`](docs/FUTURE.md)).

## Install

gander is not on PyPI. Install it from GitHub, pinned to a release tag:

```sh
uv add git+https://github.com/jspaulsen/gander --tag v0.1.0
```

which records it in `pyproject.toml` as below (`uv add "gander @ git+https://github.com/jspaulsen/gander@v0.1.0"`
works too, and records `rev = "v0.1.0"` instead of `tag`):

```toml
[project]
dependencies = ["gander"]

[tool.uv.sources]
gander = { git = "https://github.com/jspaulsen/gander", tag = "v0.1.0" }
```

It depends on `sqlalchemy[asyncio]>=2` and Python 3.12+. No database driver comes with
it: the sync functions use the standard library's `sqlite3`, and the async ones need
whatever async driver your engine uses (e.g. `aiosqlite` for `sqlite+aiosqlite`). While
the repository is private, installing needs git credentials for it.

## Migration files

One file per migration in a flat directory, named `<version>_<description>.sql`, where
`<version>` is a positive integer (`00001_create_users.sql`). Files are ordered by the
integer, not the string. Files not ending in `.sql`, and subdirectories, are ignored; two
files with the same version, or a `.sql` file not named that way, are an error.

```sql
-- +goose Up
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

-- +goose StatementBegin
CREATE TRIGGER users_refuse_delete BEFORE DELETE ON users
BEGIN
    SELECT RAISE(ABORT, 'users are never deleted');
END;
-- +goose StatementEnd

-- +goose Down
DROP TRIGGER users_refuse_delete;
DROP TABLE users;
```

- `-- +goose Up` starts the up section (required, exactly once); `-- +goose Down` starts
  the down section (optional, at most once). Comments and blank lines before `Up` are
  ignored; SQL there is an error.
- A statement ends at a line whose last word, before any `--` comment, ends in `;`. So
  `x; -- note` ends one, while `x;--note` or a `;` in the middle of a line does not.
- `-- +goose StatementBegin` / `-- +goose StatementEnd` wrap one statement that contains
  semicolons of its own, such as a trigger body.
- `-- +goose NO TRANSACTION` runs that file outside a transaction (see below).
- Annotations are matched as goose v3.28.0 matches them. An indented or unknown
  annotation, `ENVSUB ON`/`OFF` included, is an error.

Every file in the directory is parsed, both directions, before gander touches the
database, so a malformed file raises `MigrationParseError` naming the file and line and
nothing runs. [`docs/SPEC.md`](docs/SPEC.md) has the full rules, and
[`docs/DECISIONS.md`](docs/DECISIONS.md) the places gander deliberately differs from goose.

## Usage

Three functions, each taking a SQLAlchemy `Engine` for a SQLite database and checking out
one connection of its own:

```python
from pathlib import Path

from sqlalchemy import create_engine

from gander import get_version, migrate_down, migrate_up

engine = create_engine("sqlite:///app.db")
migrations = Path("migrations")

migrate_up(engine, migrations)  # apply every migration newer than the database
print(get_version(engine))  # 1: the current version, 0 for a fresh database
migrate_down(engine, migrations)  # roll back the current version's migration
print(get_version(engine))  # 0
```

- `migrate_up(engine, directory)` applies, in order, every migration newer than the
  largest version in the version table. On an up-to-date database it does nothing.
- `migrate_down(engine, directory)` rolls back one migration, the current version's, with
  its Down section, and deletes that version's rows from the version table.
- `get_version(engine)` returns the current version as goose computes it.

All three create the version table, with goose's seed row for version 0, when it does not
exist. Each takes a keyword-only `table=` for a version table other than
`goose_db_version`. gander logs `applied migration <file>` and
`rolled back migration <file>` at INFO on the `gander.runner` logger.

### Async

`migrate_up_async`, `migrate_down_async` and `get_version_async` take an `AsyncEngine`
and behave the same, transactions and errors included. Run the migrations at startup on
the engine the app already has, before anything queries it:

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine

from gander import migrate_up_async

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = create_async_engine("sqlite+aiosqlite:///app.db")
    await migrate_up_async(engine, MIGRATIONS)
    app.state.engine = engine
    yield
    await engine.dispose()


app = FastAPI(lifespan=lifespan)
```

The work runs on one of the engine's connections through `AsyncConnection.run_sync`, so
there is no thread to hand it to. The migration files are read and parsed on the event
loop before the connection opens, which blocks it briefly.

## Transactions

Each migration file runs in its own transaction together with its version-table insert
(or, for `migrate_down`, the delete). A failing migration leaves no partial schema and no
version row; the migrations before it in the same `migrate_up` stay applied. DDL is
transactional too: gander puts the connection in autocommit and issues `BEGIN` itself,
because Python's `sqlite3` would otherwise commit each `CREATE` or `ALTER` on its own.

A `-- +goose NO TRANSACTION` file runs statement by statement in autocommit, for SQL that
SQLite refuses inside a transaction, such as `VACUUM`. If one of its statements fails,
the statements before it stay applied and no version row is written.

**`PRAGMA foreign_keys`.** gander migrates on the connection your engine gives it, so the
engine's connect-event PRAGMAs stay in force while migrating. goose opens a connection of
its own, without them. With `PRAGMA foreign_keys=ON`, a table rebuild (create a new
table, copy, drop the old one, rename) fires the old table's `ON DELETE` actions and
foreign-key checks, which can delete or reject rows. SQLite ignores
`PRAGMA foreign_keys=OFF` inside a transaction, so a migration that needs it off must be
a `NO TRANSACTION` file (turning it back on at the end), or the migrations must run on an
engine without that PRAGMA.

gander also needs a connection with no transaction begun. An `engine_connect` listener
that runs a statement, or an engine built with SQLAlchemy's pysqlite "emit BEGIN"
recipe or with `connect_args={"autocommit": False}`, does not work: the first raises
`TransactionStateError`, the other two SQLAlchemy's `OperationalError` from a nested `BEGIN`.

## Errors

Every error gander raises subclasses `gander.GanderError`:

| Error | Raised when |
| --- | --- |
| `MigrationParseError` | A file name or file does not follow goose's format, or two files share a version. Names the file, and the line where there is one. Nothing has run. |
| `MigrationExecutionError` | The database rejects a migration's SQL, its version-table update or its commit. Names the file, and the failing SQL when a statement failed; `__cause__` is SQLAlchemy's `DBAPIError`, whose `.orig` is the driver's exception. |
| `MigrationRollbackError` | `migrate_down` finds the database at version 0, no file for the current version, or a file with no `-- +goose Down` section. |
| `UnsupportedDialectError` | The engine is for a database other than SQLite. |
| `TransactionStateError` | The connection gander checks out already has a transaction begun. |

Errors creating or reading the version table outside a migration propagate as
SQLAlchemy's own, and a missing or non-directory migration path raises `OSError`
(`FileNotFoundError`, `NotADirectoryError`).

## Existing goose databases

The version table has goose v3's shape for sqlite3, created with goose's DDL text, and
gander reads and writes it by goose's rules. A database goose migrated is picked up where
goose left off, and the goose CLI can read and continue a database gander migrated.
Switching an app over needs no change to the database or the migration files.

Where gander differs from goose:

- `migrate_down` raises on a file with no Down section; goose deletes the version row and
  leaves the schema.
- A migration file older than the newest applied version that has never been applied is
  skipped silently; goose's `up` reports it as missing.
- `get_version` returns 0 when no row is applied, where goose errors.

[`docs/DECISIONS.md`](docs/DECISIONS.md) lists the parser's differences too.

## Replacing goose-py

simulacra and hearth run goose-py from their FastAPI lifespan, in a thread, before the
database opens:

```python
from pathlib import Path

from goose_py import Goose

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def migrate(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Goose("sqlite3", str(path), str(MIGRATIONS), table="goose_db_version").up()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await asyncio.to_thread(migrate, DATABASE_PATH)
    database = Database.at(DATABASE_PATH)
    ...
    yield
```

To switch to gander:

1. Replace the dependency: `uv remove goose-py`, then the `uv add` above. The migration
   directory and the database stay as they are.
2. Make `migrate` take the app's engine, open the database first, and drop the
   `asyncio.to_thread`:

   ```python
   from pathlib import Path

   from sqlalchemy.ext.asyncio import AsyncEngine

   from gander import migrate_up_async

   MIGRATIONS = Path(__file__).resolve().parent / "migrations"


   async def migrate(engine: AsyncEngine) -> None:
       await migrate_up_async(engine, MIGRATIONS)


   @asynccontextmanager
   async def lifespan(app: FastAPI) -> AsyncIterator[None]:
       database = Database.at(DATABASE_PATH)  # creates the parent directory
       await migrate(database.engine)
       ...
       yield
   ```

Every other caller of `migrate` must change too: an `asyncio.to_thread(migrate, path)`
elsewhere (hearth's eval CLI has one) would now return a coroutine that never runs, so it
becomes `await migrate(database.engine)`, and sync callers such as schema tooling and tests
can call `migrate_up(create_engine(f"sqlite:///{path}"), MIGRATIONS)` (the parent directory
must exist).

The goose binary is no longer needed in development or CI. Remove the
`shutil.which("goose") is None and not os.environ.get("GOOSE_BINARY")` skip markers from
tests that only needed it to migrate, or they skip silently once goose is gone, and
delete tests of goose-py's own errors (`GooseNotFoundError`). Both apps' `Database` turns
`PRAGMA foreign_keys` on for every connection, so the caveat above applies to any
migration that rebuilds a table.

## Development

```sh
uv sync
uv run ruff format .
uv run ruff check .
uv run ty check
uv run pytest
```

Tests that compare against goose need goose v3.28.0 on `PATH`; they skip without it.
