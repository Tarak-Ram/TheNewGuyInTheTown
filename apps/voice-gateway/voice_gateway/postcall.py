"""Work that happens after a call has ended."""

import asyncio
import logging
import os
from uuid import UUID

import psycopg
from nguit_tools.extraction import extract_and_save
from nguit_tools.extractors import get_extractor
from psycopg.rows import dict_row

log = logging.getLogger(__name__)
EXTRACTION_TIMEOUT_SECONDS = 60


def _extract(call_id: UUID) -> None:
    with psycopg.connect(
        os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=5
    ) as conn:
        extract_and_save(conn, call_id, get_extractor())


async def extract_after_call(call_id: UUID) -> bool:
    """Reads the finished transcript and saves only facts the owner's words support.

    Best effort: a failure is logged and the comparison table keeps showing 'Not confirmed'.
    The mover can re-run it with POST /v1/calls/{id}/extract.
    """
    try:
        await asyncio.wait_for(asyncio.to_thread(_extract, call_id), EXTRACTION_TIMEOUT_SECONDS)
        return True
    except Exception:
        log.exception("fact extraction failed for call %s", call_id)
        return False
