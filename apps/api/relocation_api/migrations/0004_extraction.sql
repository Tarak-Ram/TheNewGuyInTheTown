-- Where each saved fact came from, and when a call's facts were last extracted.
ALTER TABLE call_facts
    ADD COLUMN source text,   -- 'transcript' when verified against the owner's words
    ADD COLUMN quote  text;   -- the exact words that support the value

ALTER TABLE calls
    ADD COLUMN extracted_at timestamptz,
    ADD COLUMN extractor    text;
