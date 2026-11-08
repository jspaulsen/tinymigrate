-- goose refuses to run against an empty migrations directory, so the first migration
-- does nothing. The `personas` table is the first real schema.

-- up
SELECT 1;

-- down
SELECT 1;
