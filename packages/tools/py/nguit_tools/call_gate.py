"""The single place that decides whether a call may happen.

The API, the voice gateway and (later) the worker all call these functions, so consent,
approval, opt-out and the CALLING_ENABLED switch are enforced in code, not in a prompt.
"""

import os
from dataclasses import dataclass
from uuid import UUID

import psycopg

CALL_FIELDS = (
    "rent",
    "deposit",
    "food",
    "availability",
    "sharing_type",
    "rules",
    "notice_period",
)
FINISHED = ("completed", "opted_out", "failed", "ended_by_owner", "unreachable")


class CallBlocked(Exception):
    """A call is not allowed. `reason` is a stable code; never show internals to users."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CallContext:
    call_id: UUID
    pg_id: UUID
    pg_name: str
    plan_id: UUID
    user_id: UUID
    provider: str
    language: str


def calling_enabled() -> bool:
    return os.environ.get("CALLING_ENABLED", "false").strip().lower() == "true"


def pg_is_callable(conn: psycopg.Connection, pg_id: UUID) -> bool:
    """Active PG with a live consent to AI calls. Opt-out revokes that consent."""
    row = conn.execute(
        """
        SELECT 1 FROM pgs p
        WHERE p.id = %s AND p.status = 'active'
          AND EXISTS (SELECT 1 FROM consents c
                       WHERE c.subject_type = 'pg' AND c.subject_id = p.id
                         AND c.purpose = 'ai_call' AND c.revoked_at IS NULL)
        """,
        (pg_id,),
    ).fetchone()
    return row is not None


def check_call_allowed(conn: psycopg.Connection, call_id: UUID) -> CallContext:
    """Raise CallBlocked unless this exact call may start or continue right now."""
    row = conn.execute(
        """
        SELECT c.id, c.status, c.provider, c.language, c.ended_at,
               b.status AS batch_status, b.approved_at, b.plan_id,
               p.id AS pg_id, p.name AS pg_name, mp.user_id
        FROM calls c
        JOIN call_batches b ON b.id = c.batch_id
        JOIN pgs p ON p.id = c.pg_id
        JOIN move_plans mp ON mp.id = b.plan_id
        WHERE c.id = %s
        """,
        (call_id,),
    ).fetchone()
    if row is None:
        raise CallBlocked("not_found")
    if row["batch_status"] != "approved" or row["approved_at"] is None:
        raise CallBlocked("not_approved")  # no call without the mover's approval (C-1)
    if row["ended_at"] is not None or row["status"] in FINISHED:
        raise CallBlocked("call_finished")
    if not pg_is_callable(conn, row["pg_id"]):
        raise CallBlocked("no_consent")  # disabled PG, no consent, or the owner opted out
    if row["provider"] != "web" and not calling_enabled():
        raise CallBlocked("calling_disabled")  # global switch for real phone calls
    return CallContext(
        call_id=row["id"],
        pg_id=row["pg_id"],
        pg_name=row["pg_name"],
        plan_id=row["plan_id"],
        user_id=row["user_id"],
        provider=row["provider"],
        language=row["language"],
    )
