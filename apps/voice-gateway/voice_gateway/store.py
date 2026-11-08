"""Database access for one call. Each method opens a short connection and runs in a thread."""

import asyncio
import os
from uuid import UUID

import psycopg
from nguit_tools.call_gate import CALL_FIELDS, CallContext, check_call_allowed
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def _connect() -> psycopg.Connection:
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=5)


class CallStore:
    def __init__(self, call_id: UUID):
        self.call_id = call_id

    # -- sync bodies --------------------------------------------------------------------
    def _gate(self) -> CallContext:
        with _connect() as conn:
            return check_call_allowed(conn, self.call_id)

    def _claim_token(self, jti_hash: str) -> bool:
        """Single use: only the first caller with the matching hash wins."""
        with _connect() as conn:
            row = conn.execute(
                """
                UPDATE calls SET token_used_at = now(), status = 'connecting', started_at = now()
                WHERE id = %s AND token_jti_hash = %s AND token_used_at IS NULL
                  AND status = 'approved'
                RETURNING id
                """,
                (self.call_id, jti_hash),
            ).fetchone()
            return row is not None

    def _mark_in_progress(self) -> None:
        with _connect() as conn:
            conn.execute(
                "UPDATE calls SET status = 'in_progress' WHERE id = %s AND ended_at IS NULL",
                (self.call_id,),
            )

    def _handle(self) -> str | None:
        with _connect() as conn:
            row = conn.execute(
                "SELECT resumption_handle FROM calls WHERE id = %s", (self.call_id,)
            ).fetchone()
            return row["resumption_handle"] if row else None

    def _set_handle(self, handle: str) -> None:
        with _connect() as conn:
            conn.execute(
                "UPDATE calls SET resumption_handle = %s WHERE id = %s", (handle, self.call_id)
            )

    def _segment(self, speaker: str, offset_ms: int, text: str) -> None:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO transcript_segments (call_id, speaker, offset_ms, text)"
                " VALUES (%s, %s, %s, %s)",
                (self.call_id, speaker, offset_ms, text),
            )

    def _fact(self, field: str, value: str, confirmed: bool, offset_ms: int) -> None:
        if field not in CALL_FIELDS:
            raise ValueError("unknown field")
        with _connect() as conn:
            # Saved the moment it is stated, so a dropped connection loses nothing.
            conn.execute(
                """
                INSERT INTO call_facts (call_id, field, value, confirmed, transcript_offset)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (call_id, field) DO UPDATE SET
                    value = EXCLUDED.value, confirmed = EXCLUDED.confirmed,
                    transcript_offset = EXCLUDED.transcript_offset
                """,
                (self.call_id, field, Jsonb(value), confirmed, offset_ms),
            )

    def _opt_out(self, pg_id: UUID, source: str) -> None:
        """Revoke the PG's consent for everyone, not just this mover."""
        with _connect() as conn:
            conn.execute(
                "UPDATE consents SET revoked_at = now() WHERE subject_type = 'pg'"
                " AND subject_id = %s AND purpose = 'ai_call' AND revoked_at IS NULL",
                (pg_id,),
            )
            conn.execute(
                "INSERT INTO audit_events (actor, action, object_type, object_id, metadata)"
                " VALUES ('owner', 'owner_opt_out', 'pg', %s, %s)",
                (str(pg_id), Jsonb({"call_id": str(self.call_id), "source": source})),
            )

    def _audit(self, action: str, metadata: dict) -> None:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO audit_events (actor, action, object_type, object_id, metadata)"
                " VALUES ('voice-gateway', %s, 'call', %s, %s)",
                (action, str(self.call_id), Jsonb(metadata)),
            )

    def _finish(self, status: str, reason: str) -> None:
        with _connect() as conn:
            conn.execute(
                "UPDATE calls SET status = %s, end_reason = %s, ended_at = now()"
                " WHERE id = %s AND ended_at IS NULL",
                (status, reason, self.call_id),
            )

    # -- async wrappers -----------------------------------------------------------------
    async def gate(self) -> CallContext:
        return await asyncio.to_thread(self._gate)

    async def claim_token(self, jti_hash: str) -> bool:
        return await asyncio.to_thread(self._claim_token, jti_hash)

    async def mark_in_progress(self) -> None:
        await asyncio.to_thread(self._mark_in_progress)

    async def handle(self) -> str | None:
        return await asyncio.to_thread(self._handle)

    async def set_handle(self, handle: str) -> None:
        await asyncio.to_thread(self._set_handle, handle)

    async def segment(self, speaker: str, offset_ms: int, text: str) -> None:
        await asyncio.to_thread(self._segment, speaker, offset_ms, text)

    async def fact(self, field: str, value: str, confirmed: bool, offset_ms: int) -> None:
        await asyncio.to_thread(self._fact, field, value, confirmed, offset_ms)

    async def opt_out(self, pg_id: UUID, source: str) -> None:
        await asyncio.to_thread(self._opt_out, pg_id, source)

    async def audit(self, action: str, metadata: dict) -> None:
        await asyncio.to_thread(self._audit, action, metadata)

    async def finish(self, status: str, reason: str) -> None:
        await asyncio.to_thread(self._finish, status, reason)
