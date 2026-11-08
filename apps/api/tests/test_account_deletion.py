import uuid
from datetime import UTC, datetime, timedelta

import pytest
from agreement_pdf import make_pdf
from nguit_tools.retention import run_retention
from nguit_tools.storage import (
    AUDIO_KEY_PATTERN,
    LocalFileStore,
    get_audio_store,
)
from relocation_api.agreements import analyzer_dep, transcriber_dep
from relocation_api.main import app
from relocation_api.storage import get_store

from conftest import PLAN, sign_in

PDF = "application/pdf"
TEXT = "1. Rent. The Tenant shall pay Rs 9,000 per month. " * 6


@pytest.fixture
def stores(client, tmp_path):
    files = LocalFileStore(str(tmp_path / "agreements"))
    audio = LocalFileStore(str(tmp_path / "audio"), pattern=AUDIO_KEY_PATTERN)
    app.dependency_overrides[get_store] = lambda: files
    app.dependency_overrides[get_audio_store] = lambda: audio
    app.dependency_overrides[analyzer_dep] = lambda: None
    app.dependency_overrides[transcriber_dep] = lambda: None
    return files, audio


def delete(client, headers, confirm="DELETE"):
    return client.delete(f"/v1/me?confirm={confirm}", headers=headers)


def upload_agreement(client, headers, plan_id):
    data = make_pdf(TEXT)
    created = client.post(
        "/v1/agreements",
        json={
            "plan_id": plan_id,
            "filename": "a.pdf",
            "content_type": PDF,
            "size_bytes": len(data),
        },
        headers=headers,
    ).json()
    assert client.put(created["upload_url"], content=data).status_code == 200
    return created["id"]


def count(conn, sql, *params):
    return conn.execute(sql, params).fetchone()["n"]


def test_it_needs_sign_in_and_an_explicit_confirmation(client, stores):
    assert client.delete("/v1/me?confirm=DELETE").status_code == 401
    headers = sign_in(client, "delete-confirm-user")
    assert client.delete("/v1/me", headers=headers).status_code == 422
    assert delete(client, headers, "yes").status_code == 422
    assert client.get("/v1/me", headers=headers).status_code == 200  # still there


def test_everything_the_person_created_is_removed(client, conn, make_call, stores):
    files, audio = stores
    c = make_call()
    conn.execute(
        "INSERT INTO transcript_segments (call_id, speaker, offset_ms, text)"
        " VALUES (%s, 'owner', 1, 'hi')",
        (c.call_id,),
    )
    conn.execute(
        "INSERT INTO call_facts (call_id, field, value, confirmed)"
        " VALUES (%s, 'rent', '\"12000\"', true)",
        (c.call_id,),
    )
    conn.commit()
    agreement_id = upload_agreement(client, c.headers, c.plan_id)
    key = conn.execute("SELECT file_uri FROM agreements WHERE id=%s", (agreement_id,)).fetchone()
    assert files.read(key["file_uri"])

    res = delete(client, c.headers)

    assert res.status_code == 200
    assert res.json() == {
        "status": "deleted",
        "plans": 1,
        "calls": 1,
        "agreements": 1,
        "files_pending": 0,
    }
    plan = [c.plan_id]
    assert count(conn, "SELECT count(*) n FROM move_plans WHERE id = ANY(%s)", plan) == 0
    assert count(conn, "SELECT count(*) n FROM call_batches WHERE plan_id = ANY(%s)", plan) == 0
    assert count(conn, "SELECT count(*) n FROM calls WHERE id = %s", c.call_id) == 0
    assert (
        count(conn, "SELECT count(*) n FROM transcript_segments WHERE call_id = %s", c.call_id) == 0
    )
    assert count(conn, "SELECT count(*) n FROM call_facts WHERE call_id = %s", c.call_id) == 0
    assert count(conn, "SELECT count(*) n FROM agreements WHERE id = %s", agreement_id) == 0
    assert not (files.base / key["file_uri"]).exists()  # the stored file is gone too


def test_the_account_is_emptied_and_the_session_stops_working(client, conn, make_call, stores):
    c = make_call()
    me = client.get("/v1/me", headers=c.headers).json()
    email = me["email"]
    delete(client, c.headers)

    row = conn.execute("SELECT * FROM users WHERE id = %s", (me["id"],)).fetchone()
    assert row["deleted_at"] is not None and row["phone_hash"] is None
    assert row["email"].endswith("@deleted.invalid") and email not in row["email"]
    assert row["google_sub"] == f"deleted:{me['id']}"
    assert client.get("/v1/me", headers=c.headers).status_code == 401
    assert client.get("/v1/plans", headers=c.headers).status_code == 401
    assert delete(client, c.headers).status_code == 401  # a second delete finds nobody


def test_the_deletion_is_audited_without_any_personal_data(client, conn, make_call, stores):
    c = make_call()
    me = client.get("/v1/me", headers=c.headers).json()
    delete(client, c.headers)
    row = conn.execute(
        "SELECT actor, metadata FROM audit_events WHERE action='account_deleted' AND object_id=%s",
        (me["id"],),
    ).fetchone()
    assert row["metadata"] == {"plans": 1, "calls": 1, "files": 0}
    assert me["email"] not in str(row)


def test_other_peoples_data_is_untouched(client, conn, make_call, stores):
    mine, other = make_call(), make_call()
    delete(client, mine.headers)
    assert client.get(f"/v1/plans/{other.plan_id}", headers=other.headers).status_code == 200
    assert client.get(f"/v1/calls/{other.call_id}", headers=other.headers).status_code == 200
    from nguit_tools.call_gate import pg_is_callable

    assert pg_is_callable(conn, other.pg_id)  # the PG's own consent is not the mover's data


def test_signing_in_again_gives_a_brand_new_empty_account(client, stores):
    first = client.post("/v1/auth/google", json={"id_token": "google-comeback-user"}).json()
    headers = {"Authorization": f"Bearer {first['access_token']}"}
    client.post("/v1/plans", json=PLAN, headers=headers)
    delete(client, headers)

    again = client.post("/v1/auth/google", json={"id_token": "google-comeback-user"})
    assert again.status_code == 200
    assert again.json()["user"]["id"] != first["user"]["id"]
    fresh = {"Authorization": f"Bearer {again.json()['access_token']}"}
    assert client.get("/v1/plans", headers=fresh).json() == []


def test_audio_recordings_are_deleted_with_the_account(client, conn, make_call, stores):
    _, audio = stores
    c = make_call()
    key = f"{uuid.uuid4()}.ogg"
    audio.save(key, b"ogg")
    conn.execute("UPDATE calls SET recording_uri = %s WHERE id = %s", (key, c.call_id))
    conn.commit()
    delete(client, c.headers)
    assert not (audio.base / key).exists()


def test_a_file_that_cannot_be_deleted_does_not_undo_the_deletion(
    client, conn, make_call, tmp_path
):
    class Stuck(LocalFileStore):
        def delete(self, key):
            raise OSError("storage unavailable")

    stuck = Stuck(str(tmp_path / "agreements"))
    app.dependency_overrides[get_store] = lambda: stuck
    app.dependency_overrides[get_audio_store] = lambda: None
    app.dependency_overrides[analyzer_dep] = lambda: None
    app.dependency_overrides[transcriber_dep] = lambda: None
    c = make_call()
    agreement_id = upload_agreement(client, c.headers, c.plan_id)
    key = conn.execute("SELECT file_uri FROM agreements WHERE id=%s", (agreement_id,)).fetchone()

    res = delete(client, c.headers)

    assert res.status_code == 200 and res.json()["files_pending"] == 1
    assert count(conn, "SELECT count(*) n FROM agreements WHERE id = %s", agreement_id) == 0
    assert (stuck.base / key["file_uri"]).exists()  # still on disk, but no row points to it
    healthy = LocalFileStore(str(tmp_path / "agreements"))
    report = run_retention(conn, healthy, None, now=datetime.now(UTC) + timedelta(days=2))
    assert report.orphans_deleted >= 1 and not (healthy.base / key["file_uri"]).exists()


def test_a_user_with_nothing_can_still_delete_their_account(client, stores):
    headers = sign_in(client, "delete-empty-user")
    res = delete(client, headers)
    assert res.status_code == 200
    assert res.json() == {
        "status": "deleted",
        "plans": 0,
        "calls": 0,
        "agreements": 0,
        "files_pending": 0,
    }
