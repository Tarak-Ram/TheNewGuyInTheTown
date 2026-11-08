"""Account deletion: DELETE /v1/me, and the same logic for an operator (scripts/delete_account.py).

Everything the person created is removed at once, not in 30 days:
plans, area scores, call batches, calls, transcripts, facts, agreements and their files, and
any call audio. The user row is kept only as an empty shell (its email and sign-in id are
replaced), so audit entries that name its id still make sense without naming a person.
A record of the deletion itself is written to the audit log, with counts and no personal data.
"""

import logging
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from nguit_schemas.account import DeletionOut
from nguit_tools.storage import get_audio_store, get_store
from psycopg.types.json import Jsonb

from relocation_api.auth import current_user
from relocation_api.db import get_conn

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["account"])

CONFIRMATION = "DELETE"


def erase_user(conn: psycopg.Connection, uid: UUID, store, audio_store) -> DeletionOut:
    """Deletes everything this user created. One code path for the app and for operators."""
    plans = [r["id"] for r in conn.execute("SELECT id FROM move_plans WHERE user_id = %s", (uid,))]
    keys = [
        r["file_uri"]
        for r in conn.execute("SELECT file_uri FROM agreements WHERE plan_id = ANY(%s)", (plans,))
    ]
    audio_keys = [
        r["recording_uri"]
        for r in conn.execute(
            "SELECT c.recording_uri FROM calls c JOIN call_batches b ON b.id = c.batch_id"
            " WHERE b.plan_id = ANY(%s) AND c.recording_uri IS NOT NULL",
            (plans,),
        )
    ]

    # Database first, in one transaction. Facts, transcripts and risks go with their parents.
    calls = conn.execute(
        "DELETE FROM calls WHERE batch_id IN (SELECT id FROM call_batches WHERE plan_id = ANY(%s))"
        " RETURNING id",
        (plans,),
    ).fetchall()
    conn.execute("DELETE FROM call_batches WHERE plan_id = ANY(%s)", (plans,))
    conn.execute("DELETE FROM agreements WHERE plan_id = ANY(%s)", (plans,))
    conn.execute("DELETE FROM move_plans WHERE user_id = %s", (uid,))
    conn.execute(
        """
        UPDATE users SET email = %s, google_sub = %s, phone_hash = NULL, deleted_at = now()
        WHERE id = %s
        """,
        (f"deleted-{uid}@deleted.invalid", f"deleted:{uid}", uid),
    )
    conn.execute(
        "INSERT INTO audit_events (actor, action, object_type, object_id, metadata)"
        " VALUES (%s, 'account_deleted', 'user', %s, %s)",
        (str(uid), str(uid), Jsonb({"plans": len(plans), "calls": len(calls), "files": len(keys)})),
    )
    conn.commit()  # the data is gone from the database whatever happens to the files below

    # Then the files. One that cannot be deleted now is swept up by the daily retention job,
    # because no database row points to it any more.
    pending = 0
    for key, target in [(k, store) for k in keys] + [(k, audio_store) for k in audio_keys]:
        if target is None:
            pending += 1
            continue
        try:
            target.delete(key)
        except Exception:
            pending += 1
            log.warning("file not deleted yet", extra={"event": "account_file_pending"})
    return DeletionOut(
        status="deleted",
        plans=len(plans),
        calls=len(calls),
        agreements=len(keys),
        files_pending=pending,
    )


@router.delete("/me", response_model=DeletionOut)
def delete_me(
    confirm: str = Query(default="", description='Must be "DELETE", to avoid accidents'),
    user: dict = Depends(current_user),
    conn: psycopg.Connection = Depends(get_conn),
    store=Depends(get_store),
    audio_store=Depends(get_audio_store),
) -> DeletionOut:
    if confirm != CONFIRMATION:
        raise HTTPException(422, f"To delete your account, confirm with confirm={CONFIRMATION}.")
    return erase_user(conn, user["id"], store, audio_store)
