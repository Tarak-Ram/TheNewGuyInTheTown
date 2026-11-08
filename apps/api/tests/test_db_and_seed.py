import psycopg
import pytest
from relocation_api.crypto import decrypt_phone
from relocation_api.migrate import migrate
from relocation_api.seed import seed

EXPECTED_TABLES = {
    "users", "move_plans", "areas", "plan_area_scores", "pgs", "consents", "call_batches",
    "calls", "call_facts", "transcript_segments", "agreements", "agreement_risks", "audit_events",
}  # fmt: skip


def test_all_prd_tables_exist(conn):
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()
    assert EXPECTED_TABLES <= {r["table_name"] for r in rows}


def test_migrations_are_idempotent(database_url):
    assert migrate(database_url) == []


def test_seed_creates_8_areas_and_12_consented_fake_pgs(conn):
    seed(conn)
    seed(conn)  # running twice must not duplicate anything
    conn.commit()
    assert conn.execute("SELECT count(*) AS n FROM areas").fetchone()["n"] == 8
    seeded = conn.execute(
        "SELECT count(*) AS n FROM pgs WHERE name ~ '^TEST PG [0-9]{2} [(]fake[)]$'"
    ).fetchone()["n"]
    assert seeded == 12
    unconsented = conn.execute(
        """
        SELECT count(*) AS n FROM pgs p WHERE p.name ~ '^TEST PG [0-9]{2} [(]fake[)]$'
          AND NOT EXISTS (
            SELECT 1 FROM consents c WHERE c.subject_type = 'pg' AND c.subject_id = p.id
              AND c.purpose = 'ai_call' AND c.revoked_at IS NULL)
        """
    ).fetchone()["n"]
    assert unconsented == 0


def test_seed_pgs_are_clearly_fake_and_phones_are_encrypted(conn):
    seed(conn)
    conn.commit()
    for pg in conn.execute("SELECT name, phone_encrypted FROM pgs").fetchall():
        assert "TEST PG" in pg["name"] and "fake" in pg["name"]
        assert b"00000" not in bytes(pg["phone_encrypted"])  # not stored in plain text
        assert decrypt_phone(pg["phone_encrypted"]).startswith("+91 00000 000")


def test_every_area_rent_has_a_source_and_date(conn):
    seed(conn)
    conn.commit()
    rows = conn.execute("SELECT rent_source, rent_updated_at FROM areas").fetchall()
    assert all(r["rent_source"] and r["rent_updated_at"] for r in rows)


def test_only_one_active_consent_per_pg_and_purpose(conn):
    seed(conn)
    conn.commit()
    pg_id = conn.execute("SELECT id FROM pgs LIMIT 1").fetchone()["id"]
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            "INSERT INTO consents (subject_type, subject_id, purpose, policy_version, channel)"
            " VALUES ('pg', %s, 'ai_call', 'x', 'test')",
            (pg_id,),
        )
    conn.rollback()


def test_a_pg_cannot_be_called_twice_in_one_batch(conn):
    seed(conn)
    user = conn.execute(
        "INSERT INTO users (google_sub, email) VALUES ('s-dup', 'dup@example.com') RETURNING id"
    ).fetchone()
    plan = conn.execute(
        """
        INSERT INTO move_plans (user_id, office_address, office_location, budget_min, budget_max,
                                arrival_date)
        VALUES (%s, 'x office', ST_SetSRID(ST_MakePoint(78.3, 17.4), 4326)::geography,
                1, 2, '2026-12-01') RETURNING id
        """,
        (user["id"],),
    ).fetchone()
    batch = conn.execute(
        "INSERT INTO call_batches (plan_id) VALUES (%s) RETURNING id", (plan["id"],)
    ).fetchone()
    pg_id = conn.execute("SELECT id FROM pgs LIMIT 1").fetchone()["id"]
    conn.execute("INSERT INTO calls (batch_id, pg_id) VALUES (%s, %s)", (batch["id"], pg_id))
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("INSERT INTO calls (batch_id, pg_id) VALUES (%s, %s)", (batch["id"], pg_id))
    conn.rollback()
