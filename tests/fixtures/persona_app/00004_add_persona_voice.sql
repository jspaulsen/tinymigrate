-- up
ALTER TABLE personas ADD COLUMN voice_clip TEXT;
ALTER TABLE personas ADD COLUMN voice_transcript TEXT;

-- down
ALTER TABLE personas DROP COLUMN voice_transcript;
ALTER TABLE personas DROP COLUMN voice_clip;
