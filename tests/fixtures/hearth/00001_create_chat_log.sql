-- +goose Up
CREATE TABLE characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    first_message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE chats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL REFERENCES characters(id),
    created_at TEXT NOT NULL
);

CREATE INDEX chats_character_id ON chats(character_id);

-- The log. One row per event, never updated or deleted.
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL REFERENCES chats(id),
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX events_chat_id ON events(chat_id, id);

-- +goose StatementBegin
CREATE TRIGGER events_refuse_update BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only');
END;
-- +goose StatementEnd

-- +goose StatementBegin
CREATE TRIGGER events_refuse_delete BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only');
END;
-- +goose StatementEnd

-- +goose Down
DROP TRIGGER events_refuse_delete;
DROP TRIGGER events_refuse_update;
DROP TABLE events;
DROP TABLE chats;
DROP TABLE characters;
