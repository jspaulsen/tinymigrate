-- up
-- The settings the Settings page edits. The defaults are the ones the environment variables
-- had; nothing seeds them from the environment (decision 85).
ALTER TABLE runtime_configuration ADD COLUMN reply_max_tokens INTEGER NOT NULL DEFAULT 1024 CHECK (reply_max_tokens > 0);
ALTER TABLE runtime_configuration ADD COLUMN budget_card INTEGER NOT NULL DEFAULT 4000 CHECK (budget_card > 0);
ALTER TABLE runtime_configuration ADD COLUMN budget_summary INTEGER NOT NULL DEFAULT 2000 CHECK (budget_summary > 0);
ALTER TABLE runtime_configuration ADD COLUMN budget_recent_turns INTEGER NOT NULL DEFAULT 16000 CHECK (budget_recent_turns > 0);
ALTER TABLE runtime_configuration ADD COLUMN budget_lore INTEGER NOT NULL DEFAULT 3000 CHECK (budget_lore > 0);
ALTER TABLE runtime_configuration ADD COLUMN budget_state INTEGER NOT NULL DEFAULT 2000 CHECK (budget_state > 0);
-- The server to import from, read-only; '' means import is off.
ALTER TABLE runtime_configuration ADD COLUMN import_url TEXT NOT NULL DEFAULT '';
ALTER TABLE runtime_configuration ADD COLUMN import_user TEXT NOT NULL DEFAULT '';
-- Never returned by the API (decision 86).
ALTER TABLE runtime_configuration ADD COLUMN import_password TEXT NOT NULL DEFAULT '';

-- down
ALTER TABLE runtime_configuration DROP COLUMN import_password;
ALTER TABLE runtime_configuration DROP COLUMN import_user;
ALTER TABLE runtime_configuration DROP COLUMN import_url;
ALTER TABLE runtime_configuration DROP COLUMN budget_state;
ALTER TABLE runtime_configuration DROP COLUMN budget_lore;
ALTER TABLE runtime_configuration DROP COLUMN budget_recent_turns;
ALTER TABLE runtime_configuration DROP COLUMN budget_summary;
ALTER TABLE runtime_configuration DROP COLUMN budget_card;
ALTER TABLE runtime_configuration DROP COLUMN reply_max_tokens;
