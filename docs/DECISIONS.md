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
   empty StatementBegin/End block yields no statement, where goose silently drops the next SQL line.
