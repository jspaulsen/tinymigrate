# gander

gander applies [goose](https://github.com/pressly/goose)-compatible SQL migration files to a
database through SQLAlchemy, in plain Python with no goose binary. It reads the same
`-- +goose Up` / `-- +goose Down` files and keeps the same `goose_db_version` table, so apps
moving off goose-py keep their migrations and their databases. It is a work in progress; see
`docs/SPEC.md`.
