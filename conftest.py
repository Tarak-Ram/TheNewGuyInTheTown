import os
import uuid

import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row
from relocation_api.auth import GoogleClaims, get_token_verifier
from relocation_api.main import app
from relocation_api.migrate import migrate

ADMIN_URL = os.environ.get(
    "TEST_DATABASE_ADMIN_URL", "postgresql://postgres:postgres@localhost:5433/postgres"
)


@pytest.fixture(scope="session")
def database_url():
    """A throwaway database, migrated fresh. Skips locally if Postgres is not running."""
    name = f"relocation_test_{uuid.uuid4().hex[:8]}"
    try:
        admin = psycopg.connect(ADMIN_URL, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        if os.environ.get("REQUIRE_DB"):
            raise
        pytest.skip("Postgres is not reachable; run `docker compose up -d db`")
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = psycopg.conninfo.make_conninfo(ADMIN_URL, dbname=name)
    migrate(url)
    yield url
    admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
    admin.close()


@pytest.fixture
def conn(database_url):
    with psycopg.connect(database_url, row_factory=dict_row) as c:
        yield c


# One key for the whole run: the test database is shared, so seeded phones must stay readable.
TEST_PHONE_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret-test-secret-test-secret")
    monkeypatch.setenv("PHONE_ENCRYPTION_KEY", TEST_PHONE_KEY)


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """Every test starts with empty counters, since they all share one client address."""
    from relocation_api.ratelimit import LIMITER

    LIMITER.reset()


@pytest.fixture
def client(database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database_url)

    def fake_verifier():
        # "google-<name>" stands in for a Google ID token in tests.
        def verify(token: str) -> GoogleClaims:
            if not token.startswith("google-"):
                from fastapi import HTTPException

                raise HTTPException(401, "Invalid Google token")
            name = token.removeprefix("google-")
            return GoogleClaims(sub=f"sub-{name}", email=f"{name}@example.com")

        return verify

    app.dependency_overrides[get_token_verifier] = fake_verifier
    yield TestClient(app)
    app.dependency_overrides.clear()


def sign_in(client: TestClient, name: str) -> dict:
    res = client.post("/v1/auth/google", json={"id_token": f"google-{name}"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


PLAN = {
    "office_address": "Wipro Circle, Gachibowli, Hyderabad",
    "office_lat": 17.4401,
    "office_lng": 78.3489,
    "budget_min": 8000,
    "budget_max": 14000,
    "arrival_date": "2026-12-01",
    "needs": {"food": "veg", "commute_mode": "bike", "pg_gender": "any"},
}


# -- call fixtures, shared by the API and voice-gateway tests ------------------------------
@pytest.fixture
def new_pg(conn):
    """Creates a brand-new fake PG with live consent, so tests never share opt-out state."""
    from relocation_api.crypto import encrypt_phone

    def make() -> str:
        area = conn.execute("SELECT id FROM areas ORDER BY name LIMIT 1").fetchone()
        if area is None:
            from relocation_api.seed import seed

            seed(conn)
            area = conn.execute("SELECT id FROM areas ORDER BY name LIMIT 1").fetchone()
        n = uuid.uuid4().hex[:8]
        pg = conn.execute(
            """
            INSERT INTO pgs (name, area_id, location, phone_encrypted, status)
            VALUES (%s, %s, ST_SetSRID(ST_MakePoint(78.36, 17.46), 4326)::geography, %s, 'active')
            RETURNING id
            """,
            (f"TEST PG {n} (fake)", area["id"], encrypt_phone("+91 00000 00099")),
        ).fetchone()
        conn.execute(
            "INSERT INTO consents (subject_type, subject_id, purpose, policy_version, channel)"
            " VALUES ('pg', %s, 'ai_call', 'test', 'test')",
            (pg["id"],),
        )
        conn.commit()
        return str(pg["id"])

    return make


@pytest.fixture
def make_call(client, new_pg):
    """Builds a mover, a plan, a batch and (optionally) an approved call."""
    from types import SimpleNamespace

    def make(*, approve: bool = True):
        headers = sign_in(client, f"user{uuid.uuid4().hex[:10]}")
        plan_id = client.post("/v1/plans", json=PLAN, headers=headers).json()["id"]
        pg_id = new_pg()
        batch = client.post(
            f"/v1/plans/{plan_id}/call-batches", json={"pg_ids": [pg_id]}, headers=headers
        ).json()
        out = SimpleNamespace(headers=headers, plan_id=plan_id, pg_id=pg_id, batch_id=batch["id"])
        if approve:
            approved = client.post(f"/v1/call-batches/{batch['id']}/approve", headers=headers)
            out.call_id = approved.json()["calls"][0]["call_id"]
        return out

    return make
