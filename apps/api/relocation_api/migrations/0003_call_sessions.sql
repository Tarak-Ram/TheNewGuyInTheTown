-- Web-call session state. The token hash makes each call link single-use.
ALTER TABLE calls
    ADD COLUMN token_jti_hash   text,
    ADD COLUMN token_used_at    timestamptz,
    ADD COLUMN resumption_handle text,
    ADD COLUMN end_reason       text;

-- A fact name can only be one of the fields the PG Caller is allowed to ask about.
ALTER TABLE call_facts
    ADD CONSTRAINT call_facts_field_allowed CHECK (
        field IN ('rent', 'deposit', 'food', 'availability', 'sharing_type', 'rules',
                  'notice_period')
    );
