# gander — spec

A small, pure-Python library that applies SQL migration files to a database through
SQLAlchemy (and so SQLModel). It replaces goose-py in small apps like simulacra and hearth,
which today shell out to the `goose` Go binary at startup to run `up` on a SQLite file.

## Goals

1. **No binary.** Plain Python on top of SQLAlchemy 2.x. No subprocess, no `GOOSE_*`
   environment variables, no `.env` lookup. Everything is passed explicitly.
2. **goose-compatible files.** Existing migration directories from simulacra and hearth
   work unchanged.
3. **goose-compatible version table.** A database already migrated by goose (table
   `goose_db_version`) is picked up where goose left off, and goose can read a database
   gander migrated. Apps switch over without touching their databases.
4. **Works with SQLModel apps**, sync or async: takes a SQLAlchemy `Engine`, and an
   `AsyncEngine` (e.g. `sqlite+aiosqlite`) through an async entry point.

## Migration files

- One file per migration in a flat directory, named `<version>_<description>.sql`, where
  `<version>` is a positive integer that fits in 64 bits (`00001_create_chat_log.sql`).
  Files are ordered by the integer, not the string. Files not ending in `.sql` are
  ignored. Two files with the same version, or a `.sql` file without a numeric prefix,
  are an error.
- Annotations, as in goose:
  - `-- +goose Up` starts the up section (required, exactly once).
  - `-- +goose Down` starts the down section (optional).
  - `-- +goose StatementBegin` / `-- +goose StatementEnd` wrap one statement that
    contains semicolons (e.g. a trigger body); it is sent as a single statement.
  - `-- +goose NO TRANSACTION` runs that file outside a transaction.
  - Annotations are matched as goose v3.28.0 matches them: a line starting with `--`
    that contains a lowercase `+goose`; the annotation word is case-insensitive and
    surrounding whitespace is ignored. An indented annotation, or an unknown one
    (including goose's `ENVSUB ON`/`OFF`), is an error.
- Outside a StatementBegin/End block, a statement ends at a line whose last word before
  any `--` comment ends in `;` (so `x; -- note` ends one, `x;--note` and a `;` mid-line
  do not). Comment-only and blank lines between statements are dropped; inside a
  statement they are kept, and, as in goose, a whitespace-only line starts a statement.
  Comments and blank lines before `-- +goose Up` are ignored (simulacra's
  `00001_init.sql` has a leading comment); SQL there is an error.
- Malformed files (no Up, duplicate Up or Down, unterminated StatementBegin, trailing
  statement without `;`) raise a clear error naming the file and line. Both directions
  are checked when a file is parsed.

## Version table

Same shape goose v3 uses for sqlite3:

```sql
CREATE TABLE goose_db_version (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL,
    is_applied INTEGER NOT NULL,
    tstamp TIMESTAMP DEFAULT (datetime('now'))
);
```

Created on first use with a seed row `(version_id=0, is_applied=1)`, as goose does.
Applying a migration inserts `(version, 1)`; rolling one back deletes its row(s).
The table name is a parameter, defaulting to `goose_db_version`. Verify behaviour
against the real goose binary (v3.28.0 is installed) rather than from memory.

## Behaviour

- `up`: apply every migration newer than the largest version in the version table (goose's
  rule), in order. Each migration
  file runs in its own transaction together with its version-table insert, so a failing
  migration leaves no partial schema and no version row; earlier ones in the same run
  stay applied. `NO TRANSACTION` files run statement by statement, in autocommit.
  Running `up` on an up-to-date database does nothing.
- `down`: roll back the newest applied migration using its Down section. A migration
  with no Down section raises.
- `version`: the current version as goose computes it: walking rows newest first, the first
  version whose newest row has `is_applied = 1` (0 for a fresh database).
- Errors are subclasses of one package base exception and name the migration file.

## Out of scope for the MVP

CLI, `create` command, Go migrations, dialects other than SQLite, environment-variable
substitution, out-of-order/missing migrations, locking. See `docs/FUTURE.md`.

## Done when

simulacra's and hearth's migration directories apply cleanly with gander; a database
migrated by goose is continued by gander and the reverse; the package installs from a
GitHub tag the way goose-py does.
