-- +goose Up
ALTER TABLE personas ADD COLUMN voice_clip TEXT;
ALTER TABLE personas ADD COLUMN voice_transcript TEXT;

-- +goose Down
ALTER TABLE personas DROP COLUMN voice_transcript;
ALTER TABLE personas DROP COLUMN voice_clip;
