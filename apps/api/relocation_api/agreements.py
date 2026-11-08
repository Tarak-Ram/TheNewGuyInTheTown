"""Agreement Checker endpoints: create an upload link, upload, analyse, read the report."""

import hashlib
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import psycopg
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from nguit_schemas.agreements import (
    ALLOWED_TYPES,
    DISCLAIMER,
    AgreementCreate,
    AgreementCreated,
    AgreementStatus,
    ReportOut,
    RiskOut,
)
from nguit_tools.agreement_ai import get_analyzer, get_transcriber
from nguit_tools.agreement_files import MAX_BYTES, FileProblem, inspect_file

from relocation_api.agreement_service import run_analysis
from relocation_api.auth import current_user
from relocation_api.db import get_conn
from relocation_api.storage import LocalFileStore, get_store, key_for

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["agreements"])

UPLOAD_LINK_SECONDS = 300
RETENTION_DAYS = 90
AUDIENCE = "agreement-upload"
STATUS_NOTES = {
    "awaiting_upload": "Waiting for your file.",
    "uploaded": "File received. Ready to check.",
    "analyzing": "Checking your agreement. This usually takes under a minute.",
}


def analyzer_dep():
    return get_analyzer()  # None when no model is configured; the rules check still runs


def transcriber_dep():
    return get_transcriber()


def _secret() -> str:
    secret = os.environ.get("SESSION_SECRET")
    if not secret:
        raise HTTPException(503, "Uploads are not configured.")
    return secret


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _own_agreement(conn: psycopg.Connection, agreement_id: UUID, user_id) -> dict:
    row = conn.execute(
        """
        SELECT a.* FROM agreements a JOIN move_plans mp ON mp.id = a.plan_id
        WHERE a.id = %s AND mp.user_id = %s
        """,
        (agreement_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Agreement not found")
    return row


@router.post("/agreements", response_model=AgreementCreated, status_code=201)
def create_agreement(
    body: AgreementCreate,
    user: dict = Depends(current_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> AgreementCreated:
    """Creates the record and a short-lived, single-use upload link."""
    plan = conn.execute(
        "SELECT 1 FROM move_plans WHERE id = %s AND user_id = %s", (body.plan_id, user["id"])
    ).fetchone()
    if plan is None:
        raise HTTPException(404, "Plan not found")
    if body.content_type not in ALLOWED_TYPES:
        raise HTTPException(415, "Only PDF, JPEG and PNG files are accepted.")
    if body.size_bytes > MAX_BYTES:
        raise HTTPException(413, "The file is too large. The limit is 15 MB.")

    agreement_id = UUID(bytes=secrets.token_bytes(16), version=4)
    jti = secrets.token_urlsafe(24)
    expires = datetime.now(UTC) + timedelta(seconds=UPLOAD_LINK_SECONDS)
    token = jwt.encode(
        {"sub": str(agreement_id), "jti": jti, "aud": AUDIENCE, "exp": expires},
        _secret(),
        algorithm="HS256",
    )
    conn.execute(
        """
        INSERT INTO agreements
            (id, plan_id, pg_id, file_uri, sha256, status, filename, content_type, size_bytes,
             upload_token_hash, upload_expires_at, delete_after)
        VALUES (%s, %s, %s, %s, '', 'awaiting_upload', %s, %s, %s, %s, %s, %s)
        """,
        (
            agreement_id, body.plan_id, body.pg_id, key_for(agreement_id, body.content_type),
            body.filename, body.content_type, body.size_bytes, _hash(jti), expires,
            datetime.now(UTC) + timedelta(days=RETENTION_DAYS),
        ),
    )  # fmt: skip
    conn.execute(
        "INSERT INTO audit_events (actor, action, object_type, object_id) VALUES (%s, %s, %s, %s)",
        (str(user["id"]), "agreement_created", "agreement", str(agreement_id)),
    )
    return AgreementCreated(
        id=agreement_id,
        upload_url=f"/v1/agreements/{agreement_id}/file?token={token}",
        expires_in=UPLOAD_LINK_SECONDS,
        max_bytes=MAX_BYTES,
        allowed_types=list(ALLOWED_TYPES),
    )


async def _read_body(request: Request) -> bytes:
    """Reads the upload but stops as soon as it is over the size limit."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BYTES:
        raise HTTPException(413, "The file is too large. The limit is 15 MB.")
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BYTES:
            raise HTTPException(413, "The file is too large. The limit is 15 MB.")
        chunks.append(chunk)
    return b"".join(chunks)


@router.put("/agreements/{agreement_id}/file", response_model=AgreementStatus)
async def upload_file(
    agreement_id: UUID,
    request: Request,
    token: str = "",
    conn: psycopg.Connection = Depends(get_conn),
    store: LocalFileStore = Depends(get_store),
) -> AgreementStatus:
    """Receives the file. Authorised by the single-use link, like a signed storage URL."""
    try:
        claims = jwt.decode(token, _secret(), algorithms=["HS256"], audience=AUDIENCE)
    except jwt.PyJWTError:
        raise HTTPException(401, "This upload link is not valid or has expired.") from None
    if claims.get("sub") != str(agreement_id):
        raise HTTPException(401, "This upload link is not valid or has expired.")

    # Claim the link first, so it can never be used twice, even by two requests at once.
    claimed = conn.execute(
        """
        UPDATE agreements SET upload_token_hash = NULL
        WHERE id = %s AND status = 'awaiting_upload' AND upload_token_hash = %s
        RETURNING id, content_type, file_uri
        """,
        (agreement_id, _hash(claims["jti"])),
    ).fetchone()
    if claimed is None:
        raise HTTPException(409, "This upload link has already been used.")
    conn.commit()

    data = await _read_body(request)
    try:
        _, pages = inspect_file(data, claimed["content_type"])
    except FileProblem as problem:
        conn.execute(
            "UPDATE agreements SET status = 'failed', message = %s WHERE id = %s",
            (problem.message, agreement_id),
        )
        conn.commit()
        raise HTTPException(422, problem.message) from None

    store.save(claimed["file_uri"], data)
    conn.execute(
        """
        UPDATE agreements SET status = 'uploaded', message = NULL, pages = %s, size_bytes = %s,
                              sha256 = %s
        WHERE id = %s
        """,
        (pages, len(data), hashlib.sha256(data).hexdigest(), agreement_id),
    )
    return AgreementStatus(id=agreement_id, status="uploaded", message=STATUS_NOTES["uploaded"])


@router.post("/agreements/{agreement_id}/analyze", response_model=AgreementStatus, status_code=202)
def analyze(
    agreement_id: UUID,
    background: BackgroundTasks,
    user: dict = Depends(current_user),
    conn: psycopg.Connection = Depends(get_conn),
    store: LocalFileStore = Depends(get_store),
    analyzer=Depends(analyzer_dep),
    transcriber=Depends(transcriber_dep),
) -> AgreementStatus:
    row = _own_agreement(conn, agreement_id, user["id"])
    claimed = conn.execute(
        """
        UPDATE agreements SET status = 'analyzing', message = NULL
        WHERE id = %s AND status IN ('uploaded', 'failed', 'unreadable', 'done')
          AND sha256 <> ''
        RETURNING id
        """,
        (agreement_id,),
    ).fetchone()
    if claimed is None:
        if row["status"] == "analyzing":
            return AgreementStatus(
                id=agreement_id, status="analyzing", message=STATUS_NOTES["analyzing"]
            )
        raise HTTPException(409, "Upload the file first.")
    conn.commit()  # the background task opens its own connection
    background.add_task(
        run_analysis,
        agreement_id,
        store=store,
        analyzer=analyzer,
        transcriber=transcriber,
    )
    return AgreementStatus(id=agreement_id, status="analyzing", message=STATUS_NOTES["analyzing"])


@router.get("/agreements/{agreement_id}/report", response_model=ReportOut)
def report(
    agreement_id: UUID,
    user: dict = Depends(current_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> ReportOut:
    a = _own_agreement(conn, agreement_id, user["id"])
    risks = conn.execute(
        """
        SELECT type, severity, page, quote, quote_translation, explanation, question_to_ask, source
        FROM agreement_risks WHERE agreement_id = %s
        ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, page, id
        """,
        (agreement_id,),
    ).fetchall()
    counts = {"high": 0, "medium": 0, "low": 0}
    for r in risks:
        counts[r["severity"]] += 1
    warnings = []
    if a["status"] == "done" and a["text_source"] == "model_transcription":
        warnings.append(
            "This was read from a photo or scan, so the wording may contain small mistakes. "
            "Check each quote against your copy."
        )
    if a["injection_detected"]:
        warnings.append(
            "This document contains text that tries to give instructions to an AI. "
            "It was ignored. Ask the owner about it."
        )
    return ReportOut(
        id=a["id"],
        status=a["status"],
        message=a["message"] or STATUS_NOTES.get(a["status"]),
        disclaimer=DISCLAIMER,
        filename=a["filename"],
        pages=a["pages"],
        text_source=a["text_source"],
        language=a["language"],
        injection_detected=a["injection_detected"],
        warnings=warnings,
        risk_counts=counts,
        risks=[RiskOut(**r) for r in risks],
        created_at=a["created_at"],
    )
