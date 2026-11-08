# Future ideas (not in the MVP)

- CLI (`tinymigrate up|down|status|create`).
- `create` helper that writes a timestamped or numbered migration skeleton.
- PostgreSQL (and other dialect) version tables.
- `migrate_up_to(version)` / `migrate_down_to(version)`, `status` listing.
- Out-of-order / missing-migration detection (`allow_missing`).
- Locking for concurrent migrators.
- Turn `PRAGMA foreign_keys` off while migrating, so a
  table rebuild on an app engine with `foreign_keys=ON` cannot cascade.
- Support engines using SQLAlchemy's pysqlite "emit BEGIN on begin" recipe.
- An opt-in to roll back a file with no Down section by deleting its row only.
- Public functions taking a caller's `Connection` / `AsyncConnection`, e.g. to migrate on a
  connection the app already holds.
