"""Deletes personal data when the privacy policy says it must go.

  - Agreements: 90 days after upload (each row carries its own `delete_after`).
  - Call audio: 30 days after the call ended.
  - Uploads that never arrived: after 24 hours.
  - Orphans: stored files that no database row points to, older than 24 hours. A delete that
    failed halfway, or an account deletion, can leave one behind.

It is safe to run as often as you like. Cloud Scheduler runs it daily through the worker.
A file that cannot be deleted is counted and tried again on the next run, never ignored.
"""

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)

AUDIO_DAYS = 30
STALE_UPLOAD_HOURS = 24
ORPHAN_HOURS = 24


@dataclass
class RetentionReport:
    agreements_deleted: int = 0
    stale_uploads_deleted: int = 0
    audio_deleted: int = 0
    orphans_deleted: int = 0
    file_failures: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def _delete_file(store, key: str, report: RetentionReport) -> bool:
    try:
        store.delete(key)
        return True
    except Exception:
        report.file_failures += 1
        log.warning("could not delete a stored file", extra={"event": "retention_file_failed"})
        return False


def run_retention(
    conn: psycopg.Connection, store, audio_store=None, now: datetime | None = None
) -> RetentionReport:
    now = now or datetime.now(UTC)
    report = RetentionReport()

    # 1. Agreements past their delete date, and uploads that never completed.
    expired = conn.execute(
        "SELECT id, file_uri FROM agreements WHERE delete_after IS NOT NULL AND delete_after < %s",
        (now,),
    ).fetchall()
    stale = conn.execute(
        "SELECT id, file_uri FROM agreements WHERE status = 'awaiting_upload' AND created_at < %s",
        (now - timedelta(hours=STALE_UPLOAD_HOURS),),
    ).fetchall()
    doomed = {r["id"]: r["file_uri"] for r in expired + stale}
    if doomed:
        # Rows first (risks go with them). A file that survives is caught as an orphan.
        conn.execute("DELETE FROM agreements WHERE id = ANY(%s)", (list(doomed),))
    report.agreements_deleted = len({r["id"] for r in expired})
    report.stale_uploads_deleted = len({r["id"] for r in stale} - {r["id"] for r in expired})
    conn.commit()
    for key in doomed.values():
        _delete_file(store, key, report)

    # 2. Call audio. The reference is cleared only after the file is really gone.
    if audio_store is not None:
        old = conn.execute(
            "SELECT id, recording_uri FROM calls WHERE recording_uri IS NOT NULL AND ended_at < %s",
            (now - timedelta(days=AUDIO_DAYS),),
        ).fetchall()
        for call in old:
            if _delete_file(audio_store, call["recording_uri"], report):
                conn.execute("UPDATE calls SET recording_uri = NULL WHERE id = %s", (call["id"],))
                report.audio_deleted += 1
        conn.commit()

    # 3. Orphans: files no row points to.
    referenced = {r["file_uri"] for r in conn.execute("SELECT file_uri FROM agreements")}
    cutoff = now - timedelta(hours=ORPHAN_HOURS)
    for key, modified in store.list_objects():
        if key not in referenced and modified < cutoff and _delete_file(store, key, report):
            report.orphans_deleted += 1

    conn.execute(
        "INSERT INTO audit_events (actor, action, object_type, metadata)"
        " VALUES ('retention', 'retention_run', 'system', %s)",
        (Jsonb(report.as_dict()),),
    )
    conn.commit()
    log.info("retention run finished", extra={"event": "retention_run", **report.as_dict()})
    return report
