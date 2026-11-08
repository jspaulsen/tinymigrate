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
