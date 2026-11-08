# Plan

Read `docs/SPEC.md` first. Built as a stack of small PRs, each merged to `main` before the
next starts. Each row is one GitHub issue.

| # | PR | Contents | Depends on |
|---|----|----------|------------|
| 1 | Scaffold (foundation) | uv package `gander` (src layout, `uv_build`, Python >=3.12), deps `sqlalchemy>=2`; dev group pytest, ruff, ty, sqlmodel, aiosqlite, pytest-asyncio. ruff/ty/pytest config modelled on `~/repos/simulacra/pyproject.toml`. `GanderError` base exception in `gander/errors.py`. `CLAUDE.md` with conventions. GitHub Actions CI running ruff check, ruff format --check, ty, pytest. A smoke test. | — |
| 2 | Parse migration files | `Migration` dataclass (version, name, path, up statements, down statements or None, use_transaction). `parse_migration(path)` and `collect_migrations(directory)` per SPEC "Migration files". Tests include parsing every file in `~/repos/hearth/server/src/hearth/migrations` and `~/repos/simulacra/src/simulacra/migrations`, copied into `tests/fixtures/`. | 1 |
| 3 | Apply migrations up | Version table per SPEC, `get_version(engine, *, table=...)`, `migrate_up(engine, directory, *, table=...)` with per-file transactions and NO TRANSACTION. Tests: fresh DB, idempotent rerun, failure rolls back that file only, NO TRANSACTION, fixture dirs apply; goose-compat tests (goose migrates part, gander continues; and reverse) that skip when the `goose` binary is absent. | 2 |
| 4 | Roll back | `migrate_down(engine, directory, *, table=...)` rolls back the newest applied migration; raises when it has no Down. Round-trip tests (up, down, up) over fixture dirs; goose-compat for down. | 3 |
| 5 | Async entry points | `migrate_up_async` / `migrate_down_async` / `get_version_async` over `AsyncEngine` via `run_sync`. Tests with `sqlite+aiosqlite` and a SQLModel model reading a migrated table. | 3 |
| 6 | README and release | README: install from GitHub tag, file format, sync and async usage, a migration recipe for simulacra/hearth (replacing goose-py). Version 0.1.0; tag `v0.1.0` after merge. | 4, 5 |

Names follow the user's rules: singular type names; functions open with an imperative
verb naming the operation (`migrate_up`, not `up`).
