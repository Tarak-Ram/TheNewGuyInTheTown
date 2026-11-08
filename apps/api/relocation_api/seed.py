"""Seed data: 8 Hyderabad areas and 12 clearly fake PGs.

Run:  python -m relocation_api.seed
Needs DATABASE_URL and PHONE_ENCRYPTION_KEY. Safe to run twice.

Everything here is illustrative test data, not reviewed market data:
- Area centres are approximate. Rent ranges are placeholders, labelled as such.
- PG phone numbers are of the form +91 00000 000NN. Real Indian mobile numbers
  never start with 0, so these can never reach a real person.
"""

import os

import psycopg
from psycopg.rows import dict_row

from relocation_api.crypto import encrypt_phone
from relocation_api.migrate import migrate

RENT_SOURCE = "SEED DATA - illustrative placeholder, not reviewed"
RENT_DATE = "2026-11-09"
CONSENT_POLICY = "seed-v0"

# name, lat, lng, rent_min, rent_max (INR per month, PG bed)
AREAS = [
    ("Gachibowli", 17.4401, 78.3489, 9000, 16000),
    ("Kondapur", 17.4600, 78.3640, 8000, 14000),
    ("Madhapur", 17.4486, 78.3908, 9000, 17000),
    ("HITEC City", 17.4435, 78.3772, 10000, 18000),
    ("Manikonda", 17.4034, 78.3870, 7000, 12000),
    ("Kukatpally", 17.4948, 78.3996, 6000, 11000),
    ("Miyapur", 17.4969, 78.3548, 6000, 10500),
    ("Financial District", 17.4150, 78.3400, 9500, 16500),
]

# (number, area name, lat/lng offset index)
PGS = [
    (1, "Gachibowli"), (2, "Gachibowli"), (3, "Kondapur"), (4, "Kondapur"),
    (5, "Madhapur"), (6, "HITEC City"), (7, "Manikonda"), (8, "Kukatpally"),
    (9, "Miyapur"), (10, "Financial District"), (11, "Madhapur"), (12, "Manikonda"),
]  # fmt: skip


def seed(conn: psycopg.Connection) -> None:
    for name, lat, lng, rent_min, rent_max in AREAS:
        conn.execute(
            """
            INSERT INTO areas (name, geometry, rent_min, rent_max, rent_source, rent_updated_at)
            VALUES (%s,
                    ST_Buffer(ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, 1500)::geometry,
                    %s, %s, %s, %s)
            ON CONFLICT (name) DO NOTHING
            """,
            (name, lng, lat, rent_min, rent_max, RENT_SOURCE, RENT_DATE),
        )
    areas = {r["name"]: r for r in conn.execute("SELECT id, name FROM areas").fetchall()}
    centres = {a[0]: (a[1], a[2]) for a in AREAS}

    for number, area_name in PGS:
        pg_name = f"TEST PG {number:02d} (fake)"
        if conn.execute("SELECT 1 FROM pgs WHERE name = %s", (pg_name,)).fetchone():
            continue
        lat, lng = centres[area_name]
        phone = f"+91 00000 000{number:02d}"
        pg = conn.execute(
            """
            INSERT INTO pgs (name, area_id, location, phone_encrypted, status, verified_at)
            VALUES (%s, %s,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s, 'active', now())
            RETURNING id
            """,
            (pg_name, areas[area_name]["id"], lng + number * 0.0003, lat, encrypt_phone(phone)),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO consents (subject_type, subject_id, purpose, policy_version, channel)
            VALUES ('pg', %s, 'ai_call', %s, 'seed')
            """,
            (pg["id"], CONSENT_POLICY),
        )


def main() -> None:
    url = os.environ["DATABASE_URL"]
    migrate(url)
    with psycopg.connect(url, row_factory=dict_row) as conn:
        seed(conn)
    print("Seeded 8 areas and 12 fake PGs.")


if __name__ == "__main__":
    main()
