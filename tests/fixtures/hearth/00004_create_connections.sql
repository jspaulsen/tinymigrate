-- +goose Up
-- A saved way to reach a model: an OpenAI-compatible server root (decision 28), the model name
-- it serves, and an optional API key, which the API never returns (decision 85).
CREATE TABLE connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    model TEXT NOT NULL,
    api_key TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- The settings that can change while the server runs: exactly one row (decision 84).
CREATE TABLE runtime_configuration (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    chat_connection_id INTEGER REFERENCES connections(id),
    memory_connection_id INTEGER REFERENCES connections(id)
);

INSERT INTO runtime_configuration (id) VALUES (1);

-- +goose Down
DROP TABLE runtime_configuration;
DROP TABLE connections;
