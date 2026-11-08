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
8. **Statements are split exactly as goose v3.28.0's `internal/sqlparser` splits them**, checked
   against the binary: a statement ends at a line whose last word before a `--` comment ends in
   `;`, so a `;` mid-line does not split. goose's sqlite driver runs a multi-statement string
   that Python's `sqlite3` refuses; the executor has to deal with that, not the parser.
9. **Deliberate divergences from goose's parser**, each checked against the binary: both
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
    `sqlite3.complete_statement`** at each `;`, which respects literals, comments and trigger bodies,
    and runs the pieces one by one inside the same transaction, as goose's driver runs them all.
    Statements go through `exec_driver_sql`, so `:name` or `%s` in a literal is never a parameter.
13. **Internal functions take a `Connection`; the public ones take an `Engine` and check one out.**
    The async entry points can then run the same code with `AsyncConnection.run_sync`. The SQLite
    check reads `connection.dialect.name` and raises `UnsupportedDialectError`.
    The `Connection` must be fresh (no transaction begun), since its isolation level is changed.
14. **`MigrationExecutionError` names the file and the failing SQL**, with SQLAlchemy's `DBAPIError`
    as `__cause__` (its `.orig` is the driver's exception), so sync and async drivers look the same.
    Errors creating or reading the version table outside a migration propagate as SQLAlchemy's.
