import uuid
from datetime import UTC, datetime, timedelta

import pytest
from nguit_tools.retention import AUDIO_DAYS, run_retention
from nguit_tools.storage import AUDIO_KEY_PATTERN, LocalFileStore

from conftest import PLAN, sign_in

NOW = datetime.now(UTC)


@pytest.fixture
def world(client, conn, tmp_path):
    """A plan, a file store, and helpers to add agreements and calls with chosen ages."""
    headers = sign_in(client, f"retention-{uuid.uuid4().hex[:8]}")
    plan_id = client.post("/v1/plans", json=PLAN, headers=headers).json()["id"]
    store = LocalFileStore(str(tmp_path / "agreements"))
    audio = LocalFileStore(str(tmp_path / "audio"), pattern=AUDIO_KEY_PATTERN)

    class World:
        pass

    w = World()
    w.conn, w.store, w.audio, w.plan_id = conn, store, audio, plan_id

    def agreement(*, delete_in_days=90, status="done", age_hours=1, with_file=True, risks=0):
        aid = str(uuid.uuid4())
        key = f"{aid}.pdf"
        conn.execute(
            """
            INSERT INTO agreements (id, plan_id, file_uri, sha256, status, filename, content_type,
                                    delete_after, created_at)
            VALUES (%s, %s, %s, 'x', %s, 'a.pdf', 'application/pdf', %s, %s)
            """,
            (aid, plan_id, key, status, NOW + timedelta(days=delete_in_days),
             NOW - timedelta(hours=age_hours)),
        )  # fmt: skip
        for i in range(risks):
            conn.execute(
                "INSERT INTO agreement_risks (agreement_id, type, severity, quote, explanation)"
                " VALUES (%s, 'lock_in', 'high', %s, 'x')",
                (aid, f"quote number {i} is long enough"),
            )
        if with_file:
            store.save(key, b"pdf bytes")
        conn.commit()
        return aid, key

    def call(*, ended_days_ago, with_audio=True):
        user = conn.execute("SELECT user_id FROM move_plans WHERE id = %s", (plan_id,)).fetchone()
        pg = conn.execute("SELECT id FROM pgs LIMIT 1").fetchone()
        if pg is None:
            from relocation_api.seed import seed

            seed(conn)
            pg = conn.execute("SELECT id FROM pgs LIMIT 1").fetchone()
        batch = conn.execute(
            "INSERT INTO call_batches (plan_id, approved_by, approved_at, status)"
            " VALUES (%s, %s, now(), 'approved') RETURNING id",
            (plan_id, user["user_id"]),
        ).fetchone()
        cid = str(uuid.uuid4())
        key = f"{cid}.ogg"
        conn.execute(
            "INSERT INTO calls (id, batch_id, pg_id, status, ended_at, recording_uri)"
            " VALUES (%s, %s, %s, 'completed', %s, %s)",
            (cid, batch["id"], pg["id"], NOW - timedelta(days=ended_days_ago),
             key if with_audio else None),
        )  # fmt: skip
        if with_audio:
            audio.save(key, b"ogg bytes")
        conn.commit()
        return cid, key

    w.agreement, w.call = agreement, call
    return w


def exists(conn, table, id_):
    row = conn.execute(f"SELECT 1 FROM {table} WHERE id = %s", (id_,)).fetchone()  # noqa: S608
    return row is not None


# -- agreements: 90 days --------------------------------------------------------------------------
def test_agreements_past_their_delete_date_are_removed_with_their_files_and_risks(world):
    old, old_key = world.agreement(delete_in_days=-1, risks=2)
    report = run_retention(world.conn, world.store, world.audio)
    assert report.agreements_deleted >= 1
    assert not exists(world.conn, "agreements", old)
    assert (
        world.conn.execute("SELECT 1 FROM agreement_risks WHERE agreement_id=%s", (old,)).fetchone()
        is None
    )
    assert not (world.store.base / old_key).exists()


def test_agreements_inside_their_retention_period_are_kept(world):
    keep, key = world.agreement(delete_in_days=30)
    run_retention(world.conn, world.store, world.audio)
    assert exists(world.conn, "agreements", keep) and world.store.read(key) == b"pdf bytes"


def test_uploads_that_never_arrived_are_cleaned_up_after_a_day(world):
    stale, _ = world.agreement(status="awaiting_upload", age_hours=30, with_file=False)
    fresh, _ = world.agreement(status="awaiting_upload", age_hours=2, with_file=False)
    report = run_retention(world.conn, world.store, world.audio)
    assert report.stale_uploads_deleted >= 1
    assert not exists(world.conn, "agreements", stale)
    assert exists(world.conn, "agreements", fresh)  # the person may still be uploading


# -- audio: 30 days -------------------------------------------------------------------------------
def test_audio_older_than_thirty_days_is_deleted_and_the_reference_cleared(world):
    old_call, old_key = world.call(ended_days_ago=AUDIO_DAYS + 1)
    new_call, new_key = world.call(ended_days_ago=AUDIO_DAYS - 1)
    report = run_retention(world.conn, world.store, world.audio)
    assert report.audio_deleted >= 1

    def uri(call_id):
        row = world.conn.execute("SELECT recording_uri FROM calls WHERE id=%s", (call_id,))
        return row.fetchone()["recording_uri"]

    assert uri(old_call) is None and not (world.audio.base / old_key).exists()
    assert uri(new_call) == new_key and world.audio.read(new_key) == b"ogg bytes"


def test_without_an_audio_store_recordings_are_left_alone_not_forgotten(world):
    call, key = world.call(ended_days_ago=60)
    run_retention(world.conn, world.store, None)
    row = world.conn.execute("SELECT recording_uri FROM calls WHERE id=%s", (call,)).fetchone()
    assert row["recording_uri"] == key


def test_a_failed_audio_delete_keeps_the_reference_so_it_is_retried(world):
    call, key = world.call(ended_days_ago=60)

    class Broken(LocalFileStore):
        def delete(self, key):
            raise OSError("storage unavailable")

    broken = Broken(str(world.audio.base), pattern=AUDIO_KEY_PATTERN)
    report = run_retention(world.conn, world.store, broken)
    assert report.file_failures >= 1 and report.audio_deleted == 0
    kept = world.conn.execute("SELECT recording_uri FROM calls WHERE id=%s", (call,)).fetchone()
    assert kept["recording_uri"] == key
    assert run_retention(world.conn, world.store, world.audio).audio_deleted >= 1  # next run works


# -- orphans --------------------------------------------------------------------------------------
def test_old_files_that_no_row_points_to_are_removed(world):
    orphan = f"{uuid.uuid4()}.pdf"
    world.store.save(orphan, b"left behind")
    later = NOW + timedelta(days=2)  # so the file counts as more than a day old
    report = run_retention(world.conn, world.store, world.audio, now=later)
    assert report.orphans_deleted >= 1 and not (world.store.base / orphan).exists()


def test_a_just_uploaded_file_is_not_mistaken_for_an_orphan(world):
    fresh = f"{uuid.uuid4()}.pdf"
    world.store.save(fresh, b"upload in progress")
    run_retention(world.conn, world.store, world.audio)
    assert (world.store.base / fresh).exists()


def test_files_that_a_row_points_to_are_never_orphans(world):
    keep, key = world.agreement(delete_in_days=30)
    run_retention(world.conn, world.store, world.audio, now=NOW + timedelta(days=5))
    assert world.store.read(key) == b"pdf bytes"


def test_a_file_whose_delete_failed_earlier_is_swept_up_later(world):
    gone, key = world.agreement(delete_in_days=-1)

    class Flaky(LocalFileStore):
        calls = 0

        def delete(self, key):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise OSError("transient")
            super().delete(key)

    flaky = Flaky(str(world.store.base))
    first = run_retention(world.conn, flaky, world.audio)
    assert first.file_failures >= 1 and (world.store.base / key).exists()  # the row is gone
    second = run_retention(world.conn, flaky, world.audio, now=NOW + timedelta(days=2))
    assert second.orphans_deleted >= 1 and not (world.store.base / key).exists()


# -- behaviour of the job itself ------------------------------------------------------------------
def test_running_twice_deletes_nothing_the_second_time(world):
    world.agreement(delete_in_days=-1)
    world.call(ended_days_ago=60)
    run_retention(world.conn, world.store, world.audio)
    again = run_retention(world.conn, world.store, world.audio)
    assert again.as_dict() == {k: 0 for k in again.as_dict()}


def test_each_run_is_written_to_the_audit_log(world):
    world.agreement(delete_in_days=-1)
    report = run_retention(world.conn, world.store, world.audio)
    row = world.conn.execute(
        "SELECT metadata FROM audit_events WHERE action='retention_run' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["metadata"]["agreements_deleted"] == report.agreements_deleted >= 1


def test_the_worker_endpoint_runs_the_job(world, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from relocation_worker.main import app

    gone, key = world.agreement(delete_in_days=-1)
    monkeypatch.delenv("DOCUMENT_BUCKET", raising=False)
    monkeypatch.delenv("AUDIO_BUCKET", raising=False)
    monkeypatch.setenv("AGREEMENT_STORAGE_DIR", str(world.store.base))
    res = TestClient(app).post("/internal/retention/run")
    assert res.status_code == 200
    assert res.json()["agreements_deleted"] >= 1
    assert not exists(world.conn, "agreements", gone)
