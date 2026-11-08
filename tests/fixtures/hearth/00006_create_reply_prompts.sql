-- +goose Up
-- The prompt behind every stored reply: one row per reply version, so each swipe has its own
-- (decision 95). Written with the reply's event. A debugging record like last_prompts: not
-- memory, and not part of the log, so rows go when their message is deleted.
CREATE TABLE reply_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL REFERENCES chats(id),
    -- The reply's message, and which of its swipes this reply became. Swipes are only appended.
    message_id INTEGER NOT NULL REFERENCES events(id),
    swipe_index INTEGER NOT NULL,
    -- The message_added or swipe_added event that stored the reply.
    reply_event_id INTEGER NOT NULL REFERENCES events(id),
    built_at TEXT NOT NULL,
    -- The chat role's connection when the prompt was built, as named then; NULL if it had none.
    connection_name TEXT,
    -- The server root the reply went to (decision 28).
    url TEXT NOT NULL,
    model TEXT NOT NULL,
    model_settings TEXT NOT NULL,   -- JSON: the model settings the request carried
    window_start_message_id INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,  -- counted with /tokenize, as the prompt view shows it
    -- What the server's usage reported; NULL when the stream ended before it (a stopped reply).
    reported_prompt_tokens INTEGER,
    slots TEXT NOT NULL,            -- JSON list of SlotRecord (context-assembly.md)
    messages TEXT NOT NULL,         -- JSON list of {role, content}: exactly what was sent
    state_sheet TEXT NOT NULL,      -- JSON StateSheet the state slot was rendered from
    first_token_seconds REAL NOT NULL,
    generation_seconds REAL NOT NULL
);

CREATE UNIQUE INDEX reply_prompts_swipe ON reply_prompts(message_id, swipe_index);

-- Shows "View prompt" on each reply in the web app. Recording doesn't read it.
ALTER TABLE runtime_configuration ADD COLUMN show_reply_prompts INTEGER NOT NULL DEFAULT 0 CHECK (show_reply_prompts IN (0, 1));

-- +goose Down
ALTER TABLE runtime_configuration DROP COLUMN show_reply_prompts;
DROP TABLE reply_prompts;
