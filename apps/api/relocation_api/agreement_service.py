"""Runs one agreement check from start to finish and saves the result."""

import logging
import os
from uuid import UUID

import psycopg
from nguit_schemas.agreements import DISCLAIMER  # noqa: F401  (re-exported for callers)
from nguit_tools.agreement_ai import GeminiTranscriber, TranscriptionFailed
from nguit_tools.agreement_check import (
    Analyzer,
    PageText,
    analyze_document,
    is_readable,
)
from nguit_tools.agreement_files import pdf_text_pages
from psycopg.rows import dict_row

from relocation_api.storage import LocalFileStore

log = logging.getLogger(__name__)

UNREADABLE = (
    "We could not read this file well enough to check it. Please upload a clearer photo, "
    "taken in good light with the whole page in view, or the original PDF."
)
NO_READER = (
    "This file needs the AI reader to read it, and that is not available right now. "
    "Please upload the original PDF instead, or try again later."
)


def _set(
    conn: psycopg.Connection, agreement_id: UUID, status: str, message: str | None, **cols
) -> None:
    sets = ["status = %s", "message = %s"] + [f"{k} = %s" for k in cols]
    conn.execute(
        f"UPDATE agreements SET {', '.join(sets)} WHERE id = %s",  # noqa: S608 - fixed column names
        [status, message, *cols.values(), agreement_id],
    )


def run_analysis(
    agreement_id: UUID,
    *,
    store: LocalFileStore,
    analyzer: Analyzer | None,
    transcriber: GeminiTranscriber | None,
) -> str:
    """Reads the file, checks it, and saves the outcome. Never raises; returns the final status."""
    try:
        with psycopg.connect(
            os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=5
        ) as conn:
            return _run(conn, agreement_id, store, analyzer, transcriber)
    except Exception:
        log.exception("agreement %s: analysis crashed", agreement_id)
        try:
            with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5) as conn:
                _set(
                    conn,
                    agreement_id,
                    "failed",
                    "Something went wrong while checking this file. Please try again.",
                )
        except Exception:
            log.exception("agreement %s: could not record the failure", agreement_id)
        return "failed"


def _run(conn, agreement_id, store, analyzer, transcriber) -> str:
    row = conn.execute(
        "SELECT id, plan_id, file_uri, content_type FROM agreements WHERE id = %s", (agreement_id,)
    ).fetchone()
    data = store.read(row["file_uri"])

    pages: list[PageText] = []
    source = "pdf_text_layer"
    language = None
    if row["content_type"] == "application/pdf":
        pages = pdf_text_pages(data)  # independent of any model
    if not is_readable(pages):
        # A photo, or a scanned PDF with no text layer: a separate transcription pass reads it.
        source = "model_transcription"
        if transcriber is None:
            _set(conn, agreement_id, "failed", NO_READER, text_source=None)
            return "failed"
        try:
            pages, language = transcriber.transcribe(data, row["content_type"])
        except TranscriptionFailed:
            _set(conn, agreement_id, "failed", NO_READER, text_source=None)
            return "failed"
        if not is_readable(pages):
            # Analyse nothing from an unreadable image, rather than guess.
            _set(conn, agreement_id, "unreadable", UNREADABLE, text_source=source)
            conn.execute("DELETE FROM agreement_risks WHERE agreement_id = %s", (agreement_id,))
            return "unreadable"

    result = analyze_document(pages, analyzer)
    conn.execute("DELETE FROM agreement_risks WHERE agreement_id = %s", (agreement_id,))
    for r in result.risks:
        conn.execute(
            """
            INSERT INTO agreement_risks
                (agreement_id, type, severity, page, quote, explanation, question_to_ask,
                 quote_translation, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                agreement_id, r.type, r.severity, r.page, r.quote, r.explanation,
                r.question_to_ask, r.quote_translation, r.source,
            ),
        )  # fmt: skip
    note = " ".join(result.warnings) or None
    _set(
        conn,
        agreement_id,
        "done",
        note,
        text_source=source,
        language=language or result.language,
        injection_detected=result.injection_detected,
        discarded_risks=result.discarded,
    )
    conn.execute("UPDATE agreements SET analyzed_at = now() WHERE id = %s", (agreement_id,))
    conn.execute(
        "INSERT INTO audit_events (actor, action, object_type, object_id, metadata)"
        " VALUES ('agreement-checker', 'agreement_analyzed', 'agreement', %s,"
        " jsonb_build_object('risks', %s::int, 'discarded', %s::int, 'injection', %s::boolean,"
        " 'model_used', %s::boolean))",
        (
            str(agreement_id),
            len(result.risks),
            result.discarded,
            result.injection_detected,
            result.used_model,
        ),
    )
    return "done"
