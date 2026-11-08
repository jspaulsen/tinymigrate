# gander — spec

A small, pure-Python library that applies SQL migration files to a database through
SQLAlchemy (and so SQLModel). It replaces goose-py in small apps like simulacra and hearth,
which today shell out to the `goose` Go binary at startup to run `up` on a SQLite file.

## Goals

1. **No binary.** Plain Python on top of SQLAlchemy 2.x. No subprocess, no `GOOSE_*`
   environment variables, no `.env` lookup. Everything is passed explicitly.
2. **Simple migration files.** gander's own small syntax (below); an app's goose files
   need their annotations rewritten once.
3. **goose-compatible version table.** A database already migrated by goose (table
   `goose_db_version`) is picked up where goose left off, and goose can read a database
   gander migrated. Apps switch over without touching their databases.
4. **Works with SQLModel apps**, sync or async: takes a SQLAlchemy `Engine`, and an
   `AsyncEngine` (e.g. `sqlite+aiosqlite`) through an async entry point.

## Migration files

gander's own syntax, not goose's: goose annotations (`-- +goose Up`, `StatementBegin`/`End`)
are ordinary comments to it.

- One file per migration in a flat directory, named `<version>_<description>.sql`, where
  `<version>` is a positive integer that fits in 64 bits (`00001_create_chat_log.sql`).
  Files are ordered by the integer, not the string. Files not ending in `.sql`, and
  subdirectories, are ignored. Two files with the same version, a `.sql` file without a
  numeric prefix, a directory with no `.sql` file, and a missing directory are an error.
- Markers, each a whole line, case-insensitive, surrounding whitespace ignored:
  - `-- up` starts the up section (required, exactly once).
  - `-- down` starts the down section (optional, at most once, after `-- up`).
  - `-- no transaction`, anywhere before `-- up`, runs that file outside a transaction.
  Any other comment is just a comment.
- Only `--` comment lines and blank lines may come before `-- up`.
- Statements are split by accumulating lines until `sqlite3.complete_statement` says the
  buffer is complete, so a trigger body (`BEGIN ... END;`) needs no marker. A section that
  ends with an incomplete statement is an error. Comments and blank lines before a
  statement belong to it; a comment-only remainder at the end of a section is dropped.
- Malformed files raise `MigrationParseError` naming the file and line. Both directions
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
  rule), in order. Each migration file runs in its own transaction together with its
  version-table insert, so a failing migration leaves no partial schema and no version
  row; earlier ones in the same run stay applied. `-- no transaction` files run statement by
  statement, in autocommit. Running `up` on an up-to-date database does nothing.
- `down`: roll back the migration of the current version (as `version` computes it) using
  its down section, in one transaction with deleting every version-table row for that
  version (`-- no transaction` files in autocommit, as for `up`). A database at version 0, a
  current version with no file in the directory, and a migration with no down section
  raise; an empty down section only deletes the rows.
- `version`: the current version as goose computes it: walking rows newest first, the first
  version whose newest row has `is_applied = 1` (0 for a fresh database).
- Errors are subclasses of one package base exception and name the migration file where
  there is one.

## Out of scope for the MVP

CLI, `create` command, Go migrations, dialects other than SQLite, out-of-order/missing
migrations, locking. See `docs/FUTURE.md`.

## Done when

simulacra's and hearth's migration directories, converted to gander's syntax, apply
cleanly; a database migrated by goose is continued by gander, and goose reads the version
gander leaves; the package installs from a GitHub tag the way goose-py does.
