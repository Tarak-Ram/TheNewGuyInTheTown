-- Agreement Checker: uploaded rental agreements and the risks found in them.
ALTER TABLE agreements
    ADD COLUMN filename            text,
    ADD COLUMN content_type        text,
    ADD COLUMN size_bytes          integer,
    ADD COLUMN text_source         text,        -- 'pdf_text_layer' or 'model_transcription'
    ADD COLUMN language            text,
    ADD COLUMN message             text,        -- plain-language note shown to the user
    ADD COLUMN injection_detected  boolean NOT NULL DEFAULT false,
    ADD COLUMN discarded_risks     integer NOT NULL DEFAULT 0,
    ADD COLUMN upload_token_hash   text,
    ADD COLUMN upload_expires_at   timestamptz,
    ADD COLUMN created_at          timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN analyzed_at         timestamptz;

ALTER TABLE agreement_risks
    ADD COLUMN quote_translation text,          -- English meaning when the clause is not English
    ADD COLUMN source            text NOT NULL DEFAULT 'model';  -- 'model' or 'rules'

CREATE INDEX agreements_plan_idx ON agreements(plan_id);
