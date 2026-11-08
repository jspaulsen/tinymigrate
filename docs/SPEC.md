# tinymigrate — spec

A small, pure-Python library that applies SQL migration files to a database through
SQLAlchemy (and so SQLModel), for small SQLModel apps that migrate a
SQLite file at startup.

## Goals

1. **No binary.** Plain Python on top of SQLAlchemy 2.x. No subprocess, no environment
   variables, no `.env` lookup. Everything is passed explicitly.
2. **Simple migration files.** tinymigrate's own small syntax (below).
3. **A simple version table** of tinymigrate's own (below).
4. **Works with SQLModel apps**, sync or async: takes a SQLAlchemy `Engine`, and an
   `AsyncEngine` (e.g. `sqlite+aiosqlite`) through an async entry point.

## Migration files

- One file per migration in a flat directory, named `<version>_<description>.sql`, where
  `<version>` is a positive integer that fits in 64 bits (`00001_create_chat_log.sql`).
  Files are ordered by the integer, not the string. Files not ending in `.sql`, and
  subdirectories, are ignored. Two files with the same version, a `.sql` file without a
  numeric prefix, a directory with no `.sql` file, and a missing directory are an error.
- Markers, each a whole line, case-insensitive, surrounding whitespace ignored:
  - `-- up` starts the up section (required, exactly once).
  - `-- down` starts the down section (optional, at most once, after `-- up`).
  - `-- no transaction`, anywhere before `-- up`, runs that file outside a transaction.
  Any other comment is just a comment, except a leftover goose annotation (`-- +goose …`),
  which is an error.
- Only `--` comment lines and blank lines may come before `-- up`.
- Statements are split by accumulating lines until `sqlite3.complete_statement` says the
  buffer is complete, so a trigger body (`BEGIN ... END;`) needs no marker. A section that
  ends with an incomplete statement, or a marker inside one, is an error. Comments before a
  statement belong to it; a comment-only remainder at the end of a section is dropped.
- Malformed files raise `MigrationParseError` naming the file and line. Both directions
  are checked when a file is parsed.

## Version table

One row per applied migration:

```sql
CREATE TABLE tinymigrate_migration (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
```

Created on first use, empty (no seed row). Applying a migration inserts its version with
`applied_at` the UTC time in ISO-8601 (`2026-11-08T12:00:00.123456+00:00`); rolling one
back deletes its row. The table name is a parameter, defaulting to `tinymigrate_migration`.

## Behaviour

- `up`: apply every migration newer than the current version, in order. Each migration
  file runs in its own transaction together with its version-table insert, so a failing
  migration leaves no partial schema and no version row; earlier ones in the same run stay
  applied. `-- no transaction` files run statement by statement, in autocommit. Running
  `up` on an up-to-date database does nothing. A file older than the current version that
  was never applied is skipped.
- `down`: roll back the migration of the current version using its down section, in one
  transaction with deleting its version-table row (`-- no transaction` files in
  autocommit, as for `up`). A database at version 0, a current version with no file in the
  directory, and a migration with no down section raise; an empty down section only
  deletes the row.
- `version`: the current version, `MAX(version)` in the version table (0 when it is empty).
- Errors are subclasses of one package base exception and name the migration file where
  there is one.

## Out of scope for the MVP

CLI, `create` command, Go migrations, dialects other than SQLite, out-of-order/missing
migrations, locking. See `docs/FUTURE.md`.

## Done when

The migration directories of two small SQLModel apps, converted to tinymigrate's syntax, apply
cleanly; a database goose migrated, adopted with the README's one-off SQL, is continued by
tinymigrate; the package installs from a GitHub tag.
