-- up
CREATE TABLE lorebooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    -- The SillyTavern world name it was imported from. NULL for a lorebook imported from a file.
    st_name TEXT UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE lore_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lorebook_id INTEGER NOT NULL REFERENCES lorebooks(id),
    -- SillyTavern's uid within its lorebook. NULL for an entry from a file without uids.
    st_uid INTEGER,
    title TEXT NOT NULL,
    keys TEXT NOT NULL,            -- JSON list of strings
    secondary_keys TEXT NOT NULL,  -- JSON list of strings; imported, unused before PR 6
    content TEXT NOT NULL,
    constant INTEGER NOT NULL,     -- 0/1: always injected
    disabled INTEGER NOT NULL,     -- 0/1: never injected
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX lore_entries_st_uid ON lore_entries(lorebook_id, st_uid) WHERE st_uid IS NOT NULL;

-- V2 card fields (reference/sillytavern.md). first_message and description exist since 00001.
ALTER TABLE characters ADD COLUMN personality TEXT NOT NULL DEFAULT '';
ALTER TABLE characters ADD COLUMN scenario TEXT NOT NULL DEFAULT '';
ALTER TABLE characters ADD COLUMN example_messages TEXT NOT NULL DEFAULT '';
ALTER TABLE characters ADD COLUMN system_prompt TEXT NOT NULL DEFAULT '';
ALTER TABLE characters ADD COLUMN post_history_instructions TEXT NOT NULL DEFAULT '';
ALTER TABLE characters ADD COLUMN creator_notes TEXT NOT NULL DEFAULT '';
ALTER TABLE characters ADD COLUMN alternate_greetings TEXT NOT NULL DEFAULT '[]';  -- JSON list
ALTER TABLE characters ADD COLUMN tags TEXT NOT NULL DEFAULT '[]';                 -- JSON list
ALTER TABLE characters ADD COLUMN character_version TEXT NOT NULL DEFAULT '';
-- The SillyTavern avatar file name, which identifies the character there. NULL if made in Hearth.
ALTER TABLE characters ADD COLUMN st_avatar TEXT;
ALTER TABLE characters ADD COLUMN lorebook_id INTEGER REFERENCES lorebooks(id);

CREATE UNIQUE INDEX characters_st_avatar ON characters(st_avatar) WHERE st_avatar IS NOT NULL;

-- Persona, copied onto the chat at creation or import. {{user}} is persona_name.
ALTER TABLE chats ADD COLUMN persona_name TEXT NOT NULL DEFAULT 'User';
ALTER TABLE chats ADD COLUMN persona_description TEXT NOT NULL DEFAULT '';
-- A live import's identity: (character avatar, chat file name). NULL for chats made in Hearth or imported from a file.
ALTER TABLE chats ADD COLUMN st_file_name TEXT;
-- The latest SillyTavern Summarize text (extra.memory) seen on import. PR 3 puts it in the summary slot.
ALTER TABLE chats ADD COLUMN imported_summary TEXT NOT NULL DEFAULT '';
-- A lorebook bound to this chat (chat_metadata.world_info, or a file import's lorebook).
ALTER TABLE chats ADD COLUMN lorebook_id INTEGER REFERENCES lorebooks(id);

CREATE UNIQUE INDEX chats_st_file_name ON chats(character_id, st_file_name) WHERE st_file_name IS NOT NULL;

-- down
DROP INDEX chats_st_file_name;
DROP INDEX characters_st_avatar;
DROP INDEX lore_entries_st_uid;
DROP TABLE lore_entries;
DROP TABLE lorebooks;
-- SQLite can't drop a column that is a foreign key, so Down leaves the added columns in place.
-- The app never migrates down; this exists so `goose down` doesn't fail on the tables.
