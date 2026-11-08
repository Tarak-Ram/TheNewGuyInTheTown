"""Turns a call transcript into checked facts.

An extractor (model or rules) only PROPOSES facts. `verify` then confirms each one against
the owner's actual words. A fact is saved as confirmed only if all of these hold:
  - the extractor says it is clear, and cites a transcript segment and an exact quote;
  - the quote really appears in that segment (or the agent line the owner said "yes" to);
  - for rent and deposit, the number is one the quote actually says;
  - the quote has no hedging ("maybe", "around") and does not look like an instruction.
Anything else is saved as value null, confirmed false, i.e. "not confirmed".
"""

import re
from dataclasses import dataclass
from typing import Literal, Protocol

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from nguit_tools.call_gate import CALL_FIELDS
from nguit_tools.numbers import parse_amounts

NUMERIC_FIELDS = ("rent", "deposit")
MAX_VALUE_CHARS = 200

HEDGE = re.compile(
    r"\b(maybe|around|approx(?:imately)?|roughly|i think|not sure|probably|might|perhaps|"
    r"something like|or so|depends|let me check|i will check|no idea|can't say|cannot say)\b|"
    r"\babout\s+\d",
    re.IGNORECASE,
)
INSTRUCTION_LIKE = re.compile(
    r"\b(ignore|disregard|forget)\b.{0,40}\b(instruction|previous|above|rules?|prompt)\b|"
    r"\bsystem\s*:|\bnew instruction|\byou (must|should|are now)\b|\bas an ai\b|"
    r"\b(set|record|save|write|mark|log)\b.{0,25}\b(as|to)\b\s*\d",
    re.IGNORECASE,
)
AFFIRMATIVE = re.compile(
    r"^\W*(yes|yeah|yep|yup|correct|right|that'?s right|that is right|exactly|sure|ok|okay|"
    r"absolutely|definitely)\W*(.{0,25})$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Segment:
    idx: int
    speaker: str  # 'owner' or 'agent'
    offset_ms: int
    text: str


class Candidate(BaseModel):
    """What an extractor proposes for one field."""

    field: Literal[
        "rent", "deposit", "food", "availability", "sharing_type", "rules", "notice_period"
    ]
    value: str | None = None
    confirmed: bool = False  # the extractor's own claim; code decides whether to believe it
    segment_index: int | None = None
    quote: str | None = None


class Extractor(Protocol):
    name: str

    def extract(self, segments: list[Segment]) -> list[Candidate]: ...


@dataclass(frozen=True)
class Fact:
    field: str
    value: int | str | None
    confirmed: bool
    transcript_offset: int | None = None
    quote: str | None = None
    source: str | None = None


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower())).strip()


def is_affirmative(text: str) -> bool:
    return bool(AFFIRMATIVE.match(text.strip()))


def _supporting_text(cand: Candidate, segments: list[Segment]) -> Segment | None:
    """The segment whose words back this candidate, or None if the quote is not supported."""
    if cand.segment_index is None or not cand.quote or not cand.quote.strip():
        return None
    by_idx = {s.idx: s for s in segments}
    seg = by_idx.get(cand.segment_index)
    if seg is None or seg.speaker != "owner":
        return None  # only the owner's words can confirm anything
    quote = _plain(cand.quote)
    if not quote:
        return None
    if quote in _plain(seg.text):
        return seg
    # "Rent is twelve thousand, right?" ... "Yes": the owner confirms the agent's statement.
    previous = by_idx.get(cand.segment_index - 1)
    if previous and previous.speaker == "agent" and is_affirmative(seg.text):
        if quote in _plain(previous.text):
            return seg
    return None


def _clean_numeric(value: str | None) -> int | None:
    if value is None:
        return None
    digits = re.sub(r"[^\d]", "", value.split(".")[0])
    return int(digits) if digits else None


def verify_candidate(cand: Candidate, segments: list[Segment]) -> Fact:
    """Decide whether one proposed fact may be saved as confirmed."""
    unconfirmed = Fact(cand.field, None, False)
    if not cand.confirmed or cand.value is None or not str(cand.value).strip():
        return unconfirmed
    seg = _supporting_text(cand, segments)
    if seg is None:
        return unconfirmed
    quote = cand.quote or ""
    if HEDGE.search(quote) or INSTRUCTION_LIKE.search(quote):
        return unconfirmed
    value: int | str
    if cand.field in NUMERIC_FIELDS:
        number = _clean_numeric(cand.value)
        # The number must be one the quoted words actually say, however it was spoken.
        if number is None or number not in parse_amounts(quote):
            return unconfirmed
        value = number
    else:
        value = str(cand.value).strip()[:MAX_VALUE_CHARS]
    return Fact(cand.field, value, True, seg.offset_ms, quote.strip(), "transcript")


def verify(candidates: list[Candidate], segments: list[Segment]) -> dict[str, Fact]:
    """One Fact per field. Only a verified candidate can replace the 'not confirmed' default."""
    facts = {f: Fact(f, None, False) for f in CALL_FIELDS}
    for cand in candidates:
        if cand.field not in facts:
            continue  # unknown field names from a model are dropped
        fact = verify_candidate(cand, segments)
        if fact.confirmed:
            facts[cand.field] = fact  # a later verified answer is a correction
    return facts


def extract_facts(segments: list[Segment], extractor: Extractor) -> dict[str, Fact]:
    """Pure: no database. Used by the pipeline and by the evals."""
    if not segments:
        return {f: Fact(f, None, False) for f in CALL_FIELDS}
    return verify(extractor.extract(segments), segments)


def load_segments(conn: psycopg.Connection, call_id) -> list[Segment]:
    rows = conn.execute(
        "SELECT speaker, offset_ms, text FROM transcript_segments"
        " WHERE call_id = %s ORDER BY offset_ms, id",
        (call_id,),
    ).fetchall()
    return [Segment(i, r["speaker"], r["offset_ms"], r["text"]) for i, r in enumerate(rows)]


def extract_and_save(conn: psycopg.Connection, call_id, extractor: Extractor) -> dict[str, Fact]:
    """Extract, verify and replace this call's facts. Safe to run again."""
    segments = load_segments(conn, call_id)
    live = {
        r["field"]: r
        for r in conn.execute(
            "SELECT field, value, confirmed FROM call_facts WHERE call_id = %s", (call_id,)
        ).fetchall()
    }
    facts = extract_facts(segments, extractor)

    # Facts the model saved during the call are never trusted on their own. Count the ones
    # the transcript does not back up, so quality problems show up in the audit log.
    disagreements = sum(1 for f, row in live.items() if row["confirmed"] and not facts[f].confirmed)
    conn.execute("DELETE FROM call_facts WHERE call_id = %s", (call_id,))
    for fact in facts.values():
        conn.execute(
            """
            INSERT INTO call_facts
                (call_id, field, value, confirmed, transcript_offset, source, quote)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                call_id,
                fact.field,
                Jsonb(fact.value) if fact.value is not None else None,
                fact.confirmed,
                fact.transcript_offset,
                fact.source,
                fact.quote,
            ),
        )
    conn.execute(
        "UPDATE calls SET extracted_at = now(), extractor = %s WHERE id = %s",
        (extractor.name, call_id),
    )
    conn.execute(
        "INSERT INTO audit_events (actor, action, object_type, object_id, metadata)"
        " VALUES ('extractor', 'facts_extracted', 'call', %s, %s)",
        (
            str(call_id),
            Jsonb(
                {
                    "extractor": extractor.name,
                    "confirmed": sum(f.confirmed for f in facts.values()),
                    "live_facts_not_backed_by_transcript": disagreements,
                }
            ),
        ),
    )
    return facts
