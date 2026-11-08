CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE users (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    google_sub  text NOT NULL UNIQUE,
    email       text NOT NULL,
    phone_hash  text,
    language    text NOT NULL DEFAULT 'en',
    created_at  timestamptz NOT NULL DEFAULT now(),
    deleted_at  timestamptz
);

CREATE TABLE move_plans (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES users(id),
    office_address  text NOT NULL,
    office_location geography(Point, 4326) NOT NULL,
    budget_min      integer NOT NULL CHECK (budget_min >= 0),
    budget_max      integer NOT NULL CHECK (budget_max >= budget_min),
    arrival_date    date NOT NULL,
    needs_json      jsonb NOT NULL DEFAULT '{}'::jsonb,
    status          text NOT NULL DEFAULT 'draft',
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX move_plans_user_idx ON move_plans(user_id);

CREATE TABLE areas (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name            text NOT NULL UNIQUE,
    geometry        geometry(Polygon, 4326) NOT NULL,
    rent_min        integer NOT NULL,
    rent_max        integer NOT NULL,
    rent_source     text NOT NULL,
    rent_updated_at date NOT NULL
);

CREATE TABLE plan_area_scores (
    plan_id         uuid NOT NULL REFERENCES move_plans(id) ON DELETE CASCADE,
    area_id         uuid NOT NULL REFERENCES areas(id),
    commute_minutes integer,
    score           real NOT NULL,
    explanation     text,
    PRIMARY KEY (plan_id, area_id)
);

CREATE TABLE pgs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name            text NOT NULL,
    area_id         uuid NOT NULL REFERENCES areas(id),
    location        geography(Point, 4326) NOT NULL,
    phone_encrypted bytea NOT NULL,
    status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    verified_at     timestamptz
);
CREATE INDEX pgs_area_idx ON pgs(area_id);

CREATE TABLE consents (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_type   text NOT NULL,
    subject_id     uuid NOT NULL,
    purpose        text NOT NULL,
    policy_version text NOT NULL,
    channel        text NOT NULL,
    granted_at     timestamptz NOT NULL DEFAULT now(),
    revoked_at     timestamptz
);
-- At most one live consent per subject and purpose. Revoking frees the slot.
CREATE UNIQUE INDEX consents_one_active
    ON consents(subject_type, subject_id, purpose) WHERE revoked_at IS NULL;

CREATE TABLE call_batches (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id     uuid NOT NULL REFERENCES move_plans(id),
    approved_by uuid REFERENCES users(id),
    approved_at timestamptz,
    status      text NOT NULL DEFAULT 'pending_approval'
);

CREATE TABLE calls (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id         uuid NOT NULL REFERENCES call_batches(id),
    pg_id            uuid NOT NULL REFERENCES pgs(id),
    provider         text NOT NULL DEFAULT 'web',
    provider_call_id text,
    language         text NOT NULL DEFAULT 'en',
    status           text NOT NULL DEFAULT 'queued',
    started_at       timestamptz,
    ended_at         timestamptz,
    recording_uri    text,
    -- Idempotency: one call per PG per batch, so a retry can never double-call.
    UNIQUE (batch_id, pg_id)
);

CREATE TABLE call_facts (
    call_id           uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    field             text NOT NULL,
    value             jsonb,
    confidence        real,
    confirmed         boolean NOT NULL DEFAULT false,
    transcript_offset integer,
    PRIMARY KEY (call_id, field)
);

CREATE TABLE transcript_segments (
    id        bigserial PRIMARY KEY,
    call_id   uuid NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    speaker   text NOT NULL,
    offset_ms integer NOT NULL,
    text      text NOT NULL
);
CREATE INDEX transcript_call_idx ON transcript_segments(call_id, offset_ms);

CREATE TABLE agreements (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id      uuid NOT NULL REFERENCES move_plans(id),
    pg_id        uuid REFERENCES pgs(id),
    file_uri     text NOT NULL,
    sha256       text NOT NULL,
    pages        integer,
    status       text NOT NULL DEFAULT 'uploaded',
    delete_after timestamptz
);

CREATE TABLE agreement_risks (
    id              bigserial PRIMARY KEY,
    agreement_id    uuid NOT NULL REFERENCES agreements(id) ON DELETE CASCADE,
    type            text NOT NULL,
    severity        text NOT NULL,
    page            integer,
    quote           text NOT NULL,
    explanation     text NOT NULL,
    question_to_ask text
);

CREATE TABLE audit_events (
    id          bigserial PRIMARY KEY,
    actor       text NOT NULL,
    action      text NOT NULL,
    object_type text NOT NULL,
    object_id   text,
    metadata    jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);
