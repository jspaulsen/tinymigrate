# Future ideas (not in the MVP)

- CLI (`gander up|down|status|create`).
- `create` helper that writes a timestamped or numbered migration skeleton.
- PostgreSQL (and other dialect) version tables.
- `migrate_up_to(version)` / `migrate_down_to(version)`, `status` listing.
- goose `-- +goose ENVSUB ON` substitution.
- Out-of-order / missing-migration detection (`allow_missing`).
- Locking for concurrent migrators.
- Replace goose-py with gander in simulacra and hearth.
