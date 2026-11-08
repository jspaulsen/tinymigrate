# Decisions

1. **Name: `gander`.** A male goose; signals goose-compatible files without claiming to be goose.
2. **Pure Python over SQLAlchemy, no goose binary.** The point of the package versus goose-py.
3. **SQLite only for the MVP.** Both target apps are SQLite. Statement execution goes through
   SQLAlchemy so other dialects are mostly a version-table DDL question; see FUTURE.md.
4. **Version table matches goose v3's `goose_db_version`.** Existing app databases keep working
   and the user can still point the goose CLI at them.
5. **Private GitHub repo `jspaulsen/gander` for now.** goose-py is public, but creating a public
   repo was blocked in this session; private is the easier-to-undo choice. Making it public
   lets apps install from a git tag without credentials. Tracked as a `decision` issue.
6. **Install from GitHub tags, not PyPI**, as goose-py does.
7. **Public functions are `migrate_up`, `migrate_down`, `get_version`** (+ `_async` variants) rather
   than goose's bare `up`/`down`, per the user's naming rules.
8. *(Superseded by 21.)* **Statements were split exactly as goose v3.28.0's `internal/sqlparser` splits them**, checked
   against the binary: a statement ends at a line whose last word before a `--` comment ends in
   `;`, so a `;` mid-line does not split. goose's sqlite driver runs a multi-statement string
   that Python's `sqlite3` refuses; the executor has to deal with that, not the parser.
9. *(Superseded by 21.)* **Deliberate divergences from goose's parser**, each checked against the binary: both
   directions are parsed and checked up front (as goose's Provider does; its CLI parses only the
   direction it runs, so `goose up` ignores an unterminated Down statement); a signed version
   (`+3_x.sql`) is rejected; `ENVSUB ON`/`OFF` is rejected rather than honoured, since running
   unsubstituted SQL would be wrong; two files with one version raise instead of goose's panic; a
   non-UTF-8 file raises; a subdirectory named like a migration is skipped where goose errors. An
   StatementBegin/End block holding nothing or only blank lines yields no statement, where goose
   sends an empty one (or, for a block with nothing in it, silently drops the next SQL line).
10. **Version table and version rules copied from goose v3.28.0's source and checked against the
    binary.** The DDL is goose's text byte for byte, so `sqlite_master` matches. `get_version` uses
    goose's `EnsureDBVersion` rule (rows newest first; a version whose newest row has
    `is_applied = 0` is skipped) and creates the table with its `(0, 1)` seed row, as `goose version`
    does; it returns 0 where goose errors because no row is applied. `migrate_up` applies what is
    newer than `MAX(version_id)`, applied or not, as goose's `up` does. goose's missing-migration
    error (a file older than that maximum with no row) is not reproduced: such a file is skipped
    silently (SPEC: out of scope; FUTURE.md).
11. **Transactions: the driver goes to autocommit and gander issues `BEGIN` itself.** pysqlite's
    legacy mode begins a transaction only before DML, so DDL would autocommit. `gander` sets
    `isolation_level="AUTOCOMMIT"` on the one `Connection` it checks out (not on the engine;
    SQLAlchemy resets it when the connection returns to the pool), sends `BEGIN` for a transactional
    file and lets SQLAlchemy's commit/rollback end it through the driver. `NO TRANSACTION` files skip
    the `BEGIN`, so each statement autocommits. Proven by tests that fail when either half is removed.
    The app's connect-event PRAGMAs (hearth's `foreign_keys=ON`, `journal_mode=WAL`) stay in force
    while migrating, unlike goose, which opens its own connection without them; `PRAGMA
    foreign_keys` is a no-op inside a transaction, so a file that needs it off must be `NO
    TRANSACTION`. An engine using SQLAlchemy's pysqlite "begin event emits BEGIN" recipe would get
    a nested `BEGIN` and fail, as would one created with Python 3.12's `connect_args={"autocommit":
    False}`; neither app uses either. The table name is interpolated unquoted, as goose does.
12. **One parsed statement may hold several SQL statements; gander splits it with
    `sqlite3.complete_statement`** at each `;` (since 21, this happens only when one line holds
    more than one, `a; b;`), which respects literals, comments and trigger bodies,
    and runs the pieces one by one inside the same transaction, as goose's driver runs them all.
    Statements go through `exec_driver_sql`, so `:name` or `%s` in a literal is never a parameter.
    A comment-only or empty piece (`SELECT 1; /* c */`, `SELECT 1;;`) still reaches the driver;
    `sqlite3` and aiosqlite both run it as a no-op, so it is not filtered out.
13. **Internal functions take a `Connection`; the public ones take an `Engine` and check one out.**
    The async entry points can then run the same code with `AsyncConnection.run_sync`. The SQLite
    check reads `connection.dialect.name` and raises `UnsupportedDialectError`.
    The `Connection` must have no transaction begun, since its isolation level is changed;
    otherwise gander raises `TransactionStateError` rather than letting SQLAlchemy's
    `InvalidRequestError` through. The public functions always check out their own connection, so
    this fires only when something on the engine begins one first (an `engine_connect` listener
    that runs a statement).
14. **`MigrationExecutionError` names the file and the failing SQL**, with SQLAlchemy's `DBAPIError`
    as `__cause__` (its `.orig` is the driver's exception), so sync and async drivers look the same.
    Errors creating or reading the version table outside a migration propagate as SQLAlchemy's.
15. **`migrate_down` follows goose v3.28.0's `down`, checked against its source and binary, except
    for a file with no Down section.** It rolls back the version `get_version` returns (so a version
    whose newest row is unapplied is passed over) and deletes every row with that `version_id`
    (goose's `DELETE ... WHERE version_id=?`), including duplicates. At version 0, or when the
    directory has no file for the current version, goose errors and changes nothing beyond creating
    its version table; gander raises `MigrationRollbackError` the same way. goose treats a file with
    no `-- +goose Down` like an empty Down section (logs `EMPTY` and deletes the row, leaving the
    schema); gander raises instead, per SPEC, since silently keeping the schema while dropping the
    row is rarely what a rollback wants. An empty Down section is still a no-op rollback, as in goose.
    Every file in the directory is parsed before rolling back, as for `up`, so a malformed older file
    blocks gander's `down` where goose's CLI parses only the current version's file.
16. **The async entry points are thin wrappers: each opens one `AsyncConnection` and hands the
    sync internals to `run_sync`.** No logic is duplicated, so the transaction scheme of decision
    11 is the same over aiosqlite (whose adapter maps `AUTOCOMMIT` and commit/rollback onto
    `sqlite3`'s); tests that fail when the `BEGIN` or the `AUTOCOMMIT` is removed run over
    `sqlite+aiosqlite` too. The dependency is `sqlalchemy[asyncio]`, which adds greenlet:
    `sqlalchemy.ext.asyncio` refuses to import without it, and `runner.py` imports `AsyncEngine`
    at module level. No async driver is a dependency; the app brings its own (aiosqlite is a dev
    dependency for the tests). Migration files are parsed before the connection opens, blocking
    the event loop briefly, as the sync functions parse before touching the database.
17. **A directory with no `.sql` file raises `MigrationParseError` naming the directory**, from
    `collect_migrations` and so from `migrate_up` and `migrate_down` (sync and async), before the
    database is touched. goose v3.28.0's `up` and `down` both fail with `no migration files found`
    and do not even create the database file; checked against the binary, and a test keeps it so.
    goose's `version` succeeds on an empty directory, and so does `get_version`, which takes no
    directory. An empty directory is how an app finds out its migrations were left out of the wheel
    or the path is wrong, so failing at startup beats starting on an unmigrated database. It reuses
    `MigrationParseError` (a directory that does not follow goose's format) rather than adding an
    error class nobody yet needs to tell apart.
18. **Paths are `str | Path`.** goose-py took the directory as a `str`, so switching apps will pass
    one. `parse_migration` and `collect_migrations` wrap their argument in `Path` once, and the
    runner hands its `directory` straight to `collect_migrations`; `os.PathLike` is not accepted
    in the annotation, since nothing passes one.
19. **The README's goose-py recipe keeps the app's blocking `migrate(path)` and swaps only the goose
    call for `migrate_up` on a throwaway sync engine.** Its `mkdir`, its thread and all its callers
    (lifespan, hearth's eval CLI, schema tooling, tests) stay as they are, and the engine has none of
    the app's PRAGMAs, as goose's own connection had none. The earlier recipe moved migrating onto the
    app's `AsyncEngine`, which broke simulacra's parent-directory test and every `to_thread` caller.
    Applied literally to a copy of simulacra with goose off `PATH`: suite, ruff and ty pass. The
    `migrate_up_async` route stays a one-paragraph alternative.
20. **`Migration`, `parse_migration` and `collect_migrations` stay exported and are documented** in
    the README, for tooling that needs the migrations without a database (a schema snapshot, a CI
    check of the directory).
21. **gander has its own migration syntax, not goose's** (supersedes 8 and 9). The user never meant
    to match goose's parser, and porting it meant porting its quirks (a `;` mid-line not
    splitting, a whitespace-only line pulling comments into a statement, annotation edge cases).
    Markers are whole lines, `-- up`, `-- down` and `-- no transaction`, case-insensitive with
    surrounding whitespace ignored; `--up` is just a comment. A leftover goose annotation (a `--`
    comment whose text starts with `+goose`, any case) is an error rather than a comment, since
    an unconverted `-- +goose Down` would otherwise put the down SQL in the up section and run it.
    A marker line while a statement is still open raises, naming both lines, rather than
    reporting the statement as incomplete. Statements are lines accumulated until
    `sqlite3.complete_statement` accepts them, so trigger bodies need no StatementBegin/End.
    Choices the issue left open: `-- no transaction` after `-- up` is an error rather than a
    comment, so a misplaced one cannot silently leave the file transactional; "comments" before
    `-- up` and in a dropped remainder mean `--` line comments, so a `/* */` block there is
    SQL before `-- up` or an incomplete statement, loud rather than silently skipped; comments
    before a statement stay part of it, and an incomplete one is reported at its first SQL
    line. A file that cannot be read, or a UTF-8 byte-order mark, are handled too: the first
    raises `MigrationParseError`, the second is skipped. The file-name rules, the 64-bit version limit, the
    UTF-8 check and keeping a lone `\r` are unchanged. goose can no longer read gander's files,
    so the tests that cross-checked parsing or file-driven runs against the goose binary are
    gone; the version-table checks against goose stay until gander owns that table too.
22. **A missing or non-directory migration path raises `MigrationParseError` naming it**, with
    the `OSError` as `__cause__`, rather than a bare `FileNotFoundError`/`NotADirectoryError`,
    so every error gander raises is a `GanderError`. goose v3.28.0's `up` and `down` also fail on
    a missing one (`nope directory does not exist`) without creating the database, which a test
    checks against the binary (goose reports a file path as `no migration files found`); gander, which
    parses before connecting, does not touch the database either. It reuses
    `MigrationParseError`, as 17 does for an empty directory.
