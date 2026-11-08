-- +goose Up
-- The name the user gave the chat. NULL until renamed: the chat is then shown under its default
-- title, the SillyTavern file name for a live import, else the character's current name.
ALTER TABLE chats ADD COLUMN title TEXT;

-- A chat's log is deleted only as a whole, with its chat (decision 99): an event may be deleted
-- once its chat row is gone, in the same transaction, with foreign keys deferred. While the chat
-- exists its events stay append-only, as before.
DROP TRIGGER events_refuse_delete;

-- +goose StatementBegin
CREATE TRIGGER events_refuse_delete BEFORE DELETE ON events
WHEN EXISTS (SELECT 1 FROM chats WHERE chats.id = OLD.chat_id)
BEGIN
    SELECT RAISE(ABORT, 'events are append-only; delete the chat to delete its log');
END;
-- +goose StatementEnd

-- +goose Down
DROP TRIGGER events_refuse_delete;

-- +goose StatementBegin
CREATE TRIGGER events_refuse_delete BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only');
END;
-- +goose StatementEnd

ALTER TABLE chats DROP COLUMN title;
