-- Cached Routes API results, so repeat rankings do not pay for the same lookup twice.
CREATE TABLE commute_cache (
    area_id    uuid NOT NULL REFERENCES areas(id),
    office_lat numeric(8, 4) NOT NULL,
    office_lng numeric(8, 4) NOT NULL,
    mode       text NOT NULL,
    daypart    text NOT NULL,
    minutes    integer NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (area_id, office_lat, office_lng, mode, daypart)
);
