# gander

Apply SQL migration files through SQLAlchemy, keeping
[goose](https://github.com/pressly/goose)'s version table, without the goose binary.

gander is plain Python on top of SQLAlchemy 2.x, so it works with SQLModel apps, sync or
async. Its migration files use a small syntax of its own (below), and it keeps goose's
`goose_db_version` table, so a database goose migrated is continued by gander. There is no
subprocess, no `GOOSE_*` environment variable and no `.env` lookup: the engine, the
directory and the table name are all passed explicitly.

SQLite only, for now. No CLI, no `create` command, no Go migrations, no
out-of-order migrations, no locking ([`docs/FUTURE.md`](docs/FUTURE.md)).

## Install

gander is not on PyPI. Install it from GitHub, pinned to a release tag:

```sh
uv add git+https://github.com/jspaulsen/gander --tag v0.1.1
```

which records it in `pyproject.toml` as below (`uv add "gander @ git+https://github.com/jspaulsen/gander@v0.1.1"`
works too, and records `rev = "v0.1.1"` instead of `tag`):

```toml
[project]
dependencies = ["gander"]

[tool.uv.sources]
gander = { git = "https://github.com/jspaulsen/gander", tag = "v0.1.1" }
```

It depends on `sqlalchemy[asyncio]>=2` and Python 3.12+. No database driver comes with
it: the sync functions use the standard library's `sqlite3`, and the async ones need
whatever async driver your engine uses (e.g. `aiosqlite` for `sqlite+aiosqlite`). While
the repository is private, installing needs git credentials for it.

## Migration files

One file per migration in a flat directory, named `<version>_<description>.sql`, where
`<version>` is a positive integer (`00001_create_users.sql`). Files are ordered by the
integer, not the string. Files not ending in `.sql`, and subdirectories, are ignored; two
files with the same version, a `.sql` file not named that way, a directory with no `.sql`
file at all, or a missing directory, are an error.

```sql
-- up
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TRIGGER users_refuse_delete BEFORE DELETE ON users
BEGIN
    SELECT RAISE(ABORT, 'users are never deleted');
END;

-- down
DROP TRIGGER users_refuse_delete;
DROP TABLE users;
```

- `-- up` starts the up section (required, exactly once); `-- down` starts the down
  section (optional, at most once, after `-- up`). Only `--` comments and blank lines may
  come before `-- up`.
- `-- no transaction`, anywhere before `-- up`, runs that file outside a transaction (see
  below).
- A marker is a whole line, case-insensitive, with surrounding whitespace ignored. Any
  other comment is just a comment, except a leftover goose annotation (`-- +goose Up`),
  which is an error.
- A statement is the lines up to the one that completes it, as `sqlite3.complete_statement`
  decides, so a `;` inside a string literal or a trigger body does not end it. Comments
  before a statement go with it; a section ending in an incomplete statement, or a marker
  inside one, is an error.

Every file in the directory is parsed, both directions, before gander touches the
database, so a malformed file raises `MigrationParseError` naming the file and line and
nothing runs. [`docs/SPEC.md`](docs/SPEC.md) has the full rules.

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

`directory` is a `Path` or a `str`.

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

### Parsing without a database

The parser the functions above use is public too, for tooling and tests that need the
migrations but no database, such as checking a migration directory in CI or generating a
schema snapshot:

- `collect_migrations(directory)` parses every `.sql` file in `directory` and returns a
  list of `Migration`, ordered by version. It raises `MigrationParseError` as
  `migrate_up` does, empty or missing directory included.
- `parse_migration(path)` parses one file into a `Migration`.
- `Migration` is a frozen dataclass: the file's `path`, the `version` and `description`
  from its name, `up_statements` and `down_statements` as tuples of SQL strings
  (`down_statements` is `None` for a file with no `-- down`, and an empty tuple for one
  with nothing under it), and `use_transaction`, `False` for a `-- no transaction` file.

```python
from gander import collect_migrations

migrations = collect_migrations("migrations")
assert all(migration.down_statements is not None for migration in migrations)
```

## Transactions

Each migration file runs in its own transaction together with its version-table insert
(or, for `migrate_down`, the delete). A failing migration leaves no partial schema and no
version row; the migrations before it in the same `migrate_up` stay applied. DDL is
transactional too: gander puts the connection in autocommit and issues `BEGIN` itself,
because Python's `sqlite3` would otherwise commit each `CREATE` or `ALTER` on its own.

A `-- no transaction` file runs statement by statement in autocommit, for SQL that
SQLite refuses inside a transaction, such as `VACUUM`. If one of its statements fails,
the statements before it stay applied and no version row is written.

**`PRAGMA foreign_keys`.** gander migrates on the connection your engine gives it, so the
engine's connect-event PRAGMAs stay in force while migrating. goose opens a connection of
its own, without them. With `PRAGMA foreign_keys=ON`, a table rebuild (create a new
table, copy, drop the old one, rename) fires the old table's `ON DELETE` actions and
foreign-key checks, which can delete or reject rows. SQLite ignores
`PRAGMA foreign_keys=OFF` inside a transaction, so a migration that needs it off must be
a `-- no transaction` file (turning it back on at the end), or the migrations must run on an
engine without that PRAGMA.

gander also needs a connection with no transaction begun. An `engine_connect` listener
that runs a statement, or an engine built with SQLAlchemy's pysqlite "emit BEGIN"
recipe or with `connect_args={"autocommit": False}`, does not work: the first raises
`TransactionStateError`, the other two SQLAlchemy's `OperationalError` from a nested `BEGIN`.

## Errors

Every error gander raises subclasses `gander.GanderError`:

| Error | Raised when |
| --- | --- |
| `MigrationParseError` | A file name or file does not follow gander's format, two files share a version, or the directory is missing, not a directory or has no `.sql` file. Names the file, and the line where there is one, or the directory. Nothing has run. |
| `MigrationExecutionError` | The database rejects a migration's SQL, its version-table update or its commit. Names the file, and the failing SQL when a statement failed; `__cause__` is SQLAlchemy's `DBAPIError`, whose `.orig` is the driver's exception. |
| `MigrationRollbackError` | `migrate_down` finds the database at version 0, no file for the current version, or a file with no `-- down` section. |
| `UnsupportedDialectError` | The engine is for a database other than SQLite. |
| `TransactionStateError` | The connection gander checks out already has a transaction begun. |

Errors creating or reading the version table outside a migration propagate as
SQLAlchemy's own.

## Existing goose databases

The version table has goose v3's shape for sqlite3, created with goose's DDL text, and
gander reads and writes it by goose's rules. A database goose migrated is picked up where
goose left off, and the goose CLI reads the version of a database gander migrated.
Switching an app over needs no change to the database; the migration files are converted
once (below), after which goose can no longer read them.

Where gander differs from goose:

- `migrate_down` raises on a file with no down section; goose deletes the version row and
  leaves the schema.
- A migration file older than the newest applied version that has never been applied is
  skipped silently; goose's `up` reports it as missing.
- `get_version` returns 0 when no row is applied, where goose errors.

## Replacing goose-py

simulacra and hearth call goose-py from a blocking `migrate`, which their FastAPI lifespan
runs in a thread before the database opens:

```python
def migrate(path: Path, *, migrations: Path = MIGRATIONS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Goose("sqlite3", str(path), str(migrations), table="goose_db_version").up()
```

To switch to gander:

1. Replace the dependency: `uv remove goose-py`, then the `uv add` above. The database
   stays as it is.
2. Convert the migration files to gander's syntax, in place: each annotation becomes its
   marker, and StatementBegin/End lines go, since a trigger body needs no marker.

   ```sh
   sed -i -e 's/^-- +goose Up$/-- up/' -e 's/^-- +goose Down$/-- down/' \
       -e 's/^-- +goose NO TRANSACTION$/-- no transaction/' \
       -e '/^-- +goose Statement\(Begin\|End\)$/d' src/<app>/migrations/*.sql
   ```

   That is GNU sed (on macOS, `gsed`), and it matches only annotations spelled exactly so;
   goose also accepted other cases and trailing whitespace. `collect_migrations` raises on
   any `+goose` left, naming its line, so run it over the directory and fix what it reports.
   A `-- +goose NO TRANSACTION` below `-- +goose Up` must move above `-- up`. goose can no
   longer read the files.
3. Replace the goose call in `migrate`, keeping its signature and its `mkdir`: gander
   creates no directories, and SQLite cannot create a database file in a missing one.

   ```python
   from pathlib import Path

   from gander import migrate_up
   from sqlalchemy import create_engine

   # Inside the package, so the wheel ships them and they resolve the same from a source tree.
   MIGRATIONS = Path(__file__).resolve().parent / "migrations"


   def migrate(path: Path, *, migrations: Path = MIGRATIONS) -> None:
       """
       Bring the SQLite database at `path` up to the newest migration in `migrations`.

       Blocking, so an async caller hands this to a thread.
       """
       path.parent.mkdir(parents=True, exist_ok=True)
       engine = create_engine(f"sqlite:///{path}")
       try:
           migrate_up(engine, migrations)
       finally:
           engine.dispose()
   ```

   hearth's `migrate(path)` takes no `migrations=` and passes `MIGRATIONS` directly; keep
   that. In the app, `gander` is a third-party package like `sqlalchemy`, so its import goes in
   the same block, sorted alphabetically, or ruff's isort (`I001`) fails. Every caller of
   `migrate` stays as it is: the lifespan's `asyncio.to_thread(migrate, path)`, hearth's
   eval CLI, schema tooling and tests. The engine is a plain one without the app's
   connect-event PRAGMAs, as goose's own connection was, so the `PRAGMA foreign_keys`
   caveat above does not apply.
4. Delete what only goose-py needed:
   - Tests of goose-py itself: the `GooseNotFoundError` test
     (`test_migrate_raises_without_goose`) and the `GOOSE_TABLE` one
     (`test_stray_goose_table_is_ignored`), which still passes but tests nothing, since
     gander reads no environment variable. The `pytest` import they used goes too.
   - Every `shutil.which("goose") is None and not os.environ.get("GOOSE_BINARY")` skip on
     a test that only needed goose to migrate, with the `os`/`shutil` imports it used and
     `pytest` where nothing else uses it, or those tests skip silently once goose is gone.
     simulacra has one, in `tests/test_schema_sync.py`; hearth has a module-level
     `pytestmark` in `test_migrate.py` (its only use of `pytest`) and `test_lifespan.py`,
     the `needs_goose` decorator in `test_eval_cli.py`, and the skip in
     `test_schema_sync.py`.
   - A CI "Install goose" step and its `GOOSE_VERSION` env (simulacra's
     `.github/workflows/ci.yml`).
   - Text naming goose-py or a required goose binary: `migrate`'s old docstring ("goose
     runs as a subprocess", "Raises goose-py's `GooseError`"), the `GooseNotFoundError`
     line in `generate_schema_sql`'s docstring (`tests/schema_tools.py` in both apps),
     simulacra's CLAUDE.md "goose-py's subprocess" example of a blocking call, and any
     README, CLAUDE.md or decisions text saying the app needs goose on `PATH` or
     `GOOSE_BINARY` (simulacra's README and CLAUDE.md; hearth's README and
     `docs/decisions.md`), and text calling the files goose migrations.

gander has no `create` command, and goose's `create` writes goose annotations, so a new migration
is written by hand: the next version, zero-padded to five digits as before
(`00005_add_thing.sql`), holding a `-- up` and a `-- down` section. Change the app's README
and CLAUDE.md to say so.

An app can instead call `migrate_up_async` on its own `AsyncEngine` and drop the thread.
Then the parent directory must exist before the engine opens the file, every
`asyncio.to_thread(migrate, ...)` caller has to change, and the engine's PRAGMAs are in
force while migrating.

## Development

```sh
uv sync
uv run ruff format .
uv run ruff check .
uv run ty check
uv run pytest
```

Tests that compare the version table against goose need goose v3.28.0 on `PATH`; they
skip without it.
