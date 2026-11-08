"""Mover-side call endpoints: list PGs, create and approve a batch, start a web call."""

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from nguit_schemas.calls import (
    ApprovalOut,
    BatchCreate,
    BatchOut,
    BatchPg,
    CallOut,
    CallSummary,
    ComparisonOut,
    ComparisonRow,
    FactOut,
    FieldCell,
    PgOut,
    WebSessionOut,
)
from nguit_tools import call_token
from nguit_tools.call_gate import CALL_FIELDS, CallBlocked, check_call_allowed, pg_is_callable
from nguit_tools.extraction import extract_and_save
from nguit_tools.extractors import get_extractor

from relocation_api.auth import current_user
from relocation_api.db import get_conn

router = APIRouter(prefix="/v1", tags=["calls"])

# A PG gets one call per plan. A second attempt is allowed once, and only after the
# first one did not connect (the mover approves that retry as a new batch).
RETRYABLE = ("unreachable", "failed")
MAX_ATTEMPTS = 2


def _own_plan(conn: psycopg.Connection, plan_id: UUID, user_id) -> None:
    row = conn.execute(
        "SELECT 1 FROM move_plans WHERE id = %s AND user_id = %s", (plan_id, user_id)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Plan not found")


def _own_batch(conn: psycopg.Connection, batch_id: UUID, user_id) -> dict:
    row = conn.execute(
        """
        SELECT b.id, b.plan_id, b.status FROM call_batches b
        JOIN move_plans mp ON mp.id = b.plan_id
        WHERE b.id = %s AND mp.user_id = %s
        """,
        (batch_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Call batch not found")
    return row


@router.get("/plans/{plan_id}/pgs", response_model=list[PgOut])
def list_pgs(
    plan_id: UUID,
    area_id: UUID | None = None,
    user: dict = Depends(current_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> list[PgOut]:
    """Only PGs that agreed to AI calls are ever listed. No phone numbers leave the server."""
    _own_plan(conn, plan_id, user["id"])
    rows = conn.execute(
        """
        SELECT p.id, p.name, a.id AS area_id, a.name AS area_name
        FROM pgs p JOIN areas a ON a.id = p.area_id
        WHERE p.status = 'active'
          AND (%(area)s::uuid IS NULL OR p.area_id = %(area)s::uuid)
          AND EXISTS (SELECT 1 FROM consents c
                       WHERE c.subject_type = 'pg' AND c.subject_id = p.id
                         AND c.purpose = 'ai_call' AND c.revoked_at IS NULL)
        ORDER BY a.name, p.name
        """,
        {"area": area_id},
    ).fetchall()
    return [PgOut(**r) for r in rows]


@router.post("/plans/{plan_id}/call-batches", response_model=BatchOut, status_code=201)
def create_batch(
    plan_id: UUID,
    body: BatchCreate,
    user: dict = Depends(current_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> BatchOut:
    """Creates a batch that does nothing until the mover approves it (C-1)."""
    _own_plan(conn, plan_id, user["id"])
    # Batches for one plan are made one at a time, so the check below sees the true state.
    # The unique index on calls is the backstop if anything ever gets past this lock.
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (str(plan_id),))
    pg_ids = list(dict.fromkeys(body.pg_ids))  # drop duplicates, keep order
    pgs = []
    for pg_id in pg_ids:
        row = conn.execute("SELECT id, name FROM pgs WHERE id = %s", (pg_id,)).fetchone()
        if row is None or not pg_is_callable(conn, pg_id):
            raise HTTPException(422, "One of these PGs cannot be called.")
        attempts = conn.execute(
            """
            SELECT count(*) AS n,
                   count(*) FILTER (WHERE c.status = ANY(%s)) AS retryable
            FROM calls c JOIN call_batches b ON b.id = c.batch_id
            WHERE b.plan_id = %s AND c.pg_id = %s
            """,
            (list(RETRYABLE), plan_id, pg_id),
        ).fetchone()
        if attempts["n"] and (
            attempts["n"] >= MAX_ATTEMPTS or attempts["retryable"] < attempts["n"]
        ):
            raise HTTPException(409, f"{row['name']} has already been called for this plan.")
        pgs.append(row)
    batch = conn.execute(
        "INSERT INTO call_batches (plan_id) VALUES (%s) RETURNING id, plan_id, status", (plan_id,)
    ).fetchone()
    for pg in pgs:
        # Recorded now, so approval covers exactly the PGs the mover was shown.
        try:
            conn.execute(
                "INSERT INTO calls (batch_id, pg_id, plan_id, provider, language, status)"
                " VALUES (%s, %s, %s, 'web', 'en', 'pending_approval')",
                (batch["id"], pg["id"], plan_id),
            )
        except psycopg.errors.UniqueViolation:
            # The database refused a second live call for this PG and plan. Nothing is kept:
            # the error leaves this request's transaction to be rolled back.
            raise HTTPException(
                409, f"{pg['name']} has already been called for this plan."
            ) from None
    conn.execute(
        "INSERT INTO audit_events (actor, action, object_type, object_id, metadata)"
        " VALUES (%s, 'call_batch_created', 'call_batch', %s, jsonb_build_object('pgs', %s::int))",
        (str(user["id"]), str(batch["id"]), len(pgs)),
    )
    return BatchOut(**batch, pgs=[BatchPg(pg_id=p["id"], name=p["name"]) for p in pgs])


@router.post("/call-batches/{batch_id}/approve", response_model=ApprovalOut)
def approve_batch(
    batch_id: UUID,
    user: dict = Depends(current_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> ApprovalOut:
    """The mover approves the exact batch they were shown. Nothing else may be called."""
    _own_batch(conn, batch_id, user["id"])
    claimed = conn.execute(
        """
        UPDATE call_batches SET status = 'approved', approved_by = %s, approved_at = now()
        WHERE id = %s AND status = 'pending_approval' RETURNING id
        """,
        (user["id"], batch_id),
    ).fetchone()
    if claimed is None:  # already approved: never queue the same calls twice
        raise HTTPException(409, "This batch has already been approved.")

    calls, skipped = [], []
    pending = conn.execute(
        """
        SELECT c.id, c.pg_id, p.name FROM calls c JOIN pgs p ON p.id = c.pg_id
        WHERE c.batch_id = %s ORDER BY p.name
        """,
        (batch_id,),
    ).fetchall()
    for row in pending:
        if pg_is_callable(conn, row["pg_id"]):
            conn.execute("UPDATE calls SET status = 'approved' WHERE id = %s", (row["id"],))
            calls.append(
                CallSummary(
                    call_id=row["id"], pg_id=row["pg_id"], pg_name=row["name"], status="approved"
                )
            )
        else:  # consent was withdrawn between creating and approving the batch
            conn.execute(
                "UPDATE calls SET status = 'failed', end_reason = 'consent_lost', ended_at = now()"
                " WHERE id = %s",
                (row["id"],),
            )
            skipped.append(row["name"])
    conn.execute(
        "INSERT INTO audit_events (actor, action, object_type, object_id, metadata)"
        " VALUES (%s, 'call_batch_approved', 'call_batch', %s,"
        " jsonb_build_object('calls', %s::int))",
        (str(user["id"]), str(batch_id), len(calls)),
    )
    return ApprovalOut(batch_id=batch_id, status="approved", calls=calls, skipped=skipped)


def _own_call(conn: psycopg.Connection, call_id: UUID, user_id) -> dict:
    row = conn.execute(
        """
        SELECT c.id, c.pg_id, p.name AS pg_name, c.status, c.language, c.started_at,
               c.ended_at, c.end_reason
        FROM calls c
        JOIN call_batches b ON b.id = c.batch_id
        JOIN move_plans mp ON mp.id = b.plan_id
        JOIN pgs p ON p.id = c.pg_id
        WHERE c.id = %s AND mp.user_id = %s
        """,
        (call_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Call not found")
    return row


@router.get("/calls/{call_id}", response_model=CallOut)
def read_call(
    call_id: UUID,
    user: dict = Depends(current_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> CallOut:
    call = _own_call(conn, call_id, user["id"])
    facts = conn.execute(
        "SELECT field, value, confirmed, transcript_offset, quote, source FROM call_facts"
        " WHERE call_id = %s ORDER BY field",
        (call_id,),
    ).fetchall()
    return CallOut(**call, facts=[FactOut(**f) for f in facts])


@router.post("/calls/{call_id}/web-session", response_model=WebSessionOut)
def start_web_session(
    call_id: UUID,
    user: dict = Depends(current_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> WebSessionOut:
    """Issues a single-use link for the browser to open the voice gateway."""
    call = _own_call(conn, call_id, user["id"])
    try:
        check_call_allowed(conn, call_id)
    except CallBlocked as blocked:
        messages = {
            "not_approved": "Approve the call batch first.",
            "call_finished": "This call has already finished.",
            "no_consent": "This PG can no longer be called.",
            "calling_disabled": "Calling is switched off.",
        }
        raise HTTPException(409, messages.get(blocked.reason, "This call cannot start.")) from None
    if call["status"] != "approved":
        # The link was already used and the call is running. A new link now would let a second
        # session open on the same call, and would reset the "used" mark on the first.
        raise HTTPException(409, "This call has already started.")
    token, jti = call_token.mint(call_id)
    conn.execute(
        "UPDATE calls SET token_jti_hash = %s, token_used_at = NULL WHERE id = %s",
        (call_token.hash_jti(jti), call_id),
    )
    return WebSessionOut(token=token, expires_in=call_token.TTL_SECONDS)


NOT_CONFIRMED = "Not confirmed"


def _display(field: str, value) -> str:
    if field in ("rent", "deposit") and isinstance(value, int):
        return f"Rs {value:,}"
    return str(value)


@router.post("/calls/{call_id}/extract", response_model=CallOut)
def extract_call(
    call_id: UUID,
    user: dict = Depends(current_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> CallOut:
    """Re-reads a finished call's transcript and saves only the facts it can back up."""
    call = _own_call(conn, call_id, user["id"])
    if call["ended_at"] is None:
        raise HTTPException(409, "The call has not finished yet.")
    extract_and_save(conn, call_id, get_extractor())
    return read_call(call_id, user, conn)


@router.get("/plans/{plan_id}/comparison", response_model=ComparisonOut)
def comparison(
    plan_id: UUID,
    user: dict = Depends(current_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> ComparisonOut:
    """One row per PG called for this plan. Anything not proven by the transcript is
    shown as 'Not confirmed', never guessed."""
    _own_plan(conn, plan_id, user["id"])
    calls = conn.execute(
        """
        SELECT DISTINCT ON (c.pg_id) c.id, c.pg_id, p.name AS pg_name, a.name AS area_name,
               c.status, c.provider, c.extracted_at
        FROM calls c
        JOIN call_batches b ON b.id = c.batch_id
        JOIN pgs p ON p.id = c.pg_id
        JOIN areas a ON a.id = p.area_id
        WHERE b.plan_id = %s AND c.status <> 'pending_approval'
        ORDER BY c.pg_id, c.started_at DESC NULLS LAST, c.id
        """,
        (plan_id,),
    ).fetchall()
    facts: dict = {}
    if calls:
        for f in conn.execute(
            "SELECT call_id, field, value, confirmed, transcript_offset, quote FROM call_facts"
            " WHERE call_id = ANY(%s)",
            ([c["id"] for c in calls],),
        ).fetchall():
            facts[(f["call_id"], f["field"])] = f

    rows = []
    for c in sorted(calls, key=lambda r: r["pg_name"]):
        checked = c["extracted_at"] is not None
        cells = {}
        for field in CALL_FIELDS:
            f = facts.get((c["id"], field))
            # Facts saved live by the model are not trusted until the transcript check ran.
            if checked and f and f["confirmed"] and f["value"] is not None:
                cells[field] = FieldCell(
                    value=f["value"],
                    confirmed=True,
                    display=_display(field, f["value"]),
                    transcript_offset=f["transcript_offset"],
                    quote=f["quote"],
                )
            else:
                cells[field] = FieldCell(value=None, confirmed=False, display=NOT_CONFIRMED)
        rows.append(
            ComparisonRow(
                pg_id=c["pg_id"],
                pg_name=c["pg_name"],
                area_name=c["area_name"],
                call_id=c["id"],
                call_status=c["status"],
                provider=c["provider"],
                facts_checked=checked,
                fields=cells,
            )
        )
    return ComparisonOut(plan_id=plan_id, field_order=list(CALL_FIELDS), rows=rows)
