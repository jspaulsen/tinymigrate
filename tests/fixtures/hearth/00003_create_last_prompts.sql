-- +goose Up
-- The prompt most recently sent for each chat: the debugging record behind the prompt view.
-- One row per chat, replaced on every reply. Not memory, and not part of the log.
CREATE TABLE last_prompts (
    chat_id INTEGER PRIMARY KEY REFERENCES chats(id),
    built_at TEXT NOT NULL,
    model TEXT NOT NULL,
    -- The oldest message in the recent-turns slot. The next prompt starts from it if it still fits,
    -- which keeps the prefix stable for llama.cpp's cache (context-assembly.md).
    window_start_message_id INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    slots TEXT NOT NULL,     -- JSON list of SlotRecord (context-assembly.md)
    messages TEXT NOT NULL   -- JSON list of {role, content}: exactly what was sent
);

-- +goose Down
DROP TABLE last_prompts;
