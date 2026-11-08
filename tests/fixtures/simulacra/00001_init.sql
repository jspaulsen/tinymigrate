-- goose refuses to run against an empty migrations directory, so the first migration
-- does nothing. The `personas` table is the first real schema.

-- +goose Up
SELECT 1;

-- +goose Down
SELECT 1;
