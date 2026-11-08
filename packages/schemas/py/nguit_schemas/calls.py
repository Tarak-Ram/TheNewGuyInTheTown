from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PgOut(BaseModel):
    id: UUID
    name: str
    area_id: UUID
    area_name: str


class BatchCreate(BaseModel):
    pg_ids: list[UUID] = Field(min_length=1, max_length=5)


class BatchPg(BaseModel):
    pg_id: UUID
    name: str


class BatchOut(BaseModel):
    id: UUID
    plan_id: UUID
    status: str
    pgs: list[BatchPg]


class CallSummary(BaseModel):
    call_id: UUID
    pg_id: UUID
    pg_name: str
    status: str


class ApprovalOut(BaseModel):
    batch_id: UUID
    status: str
    calls: list[CallSummary]
    skipped: list[str] = []  # PGs that lost consent between creating and approving


class FactOut(BaseModel):
    field: str
    value: Any
    confirmed: bool
    transcript_offset: int | None
    quote: str | None = None
    source: str | None = None


class CallOut(BaseModel):
    id: UUID
    pg_id: UUID
    pg_name: str
    status: str
    language: str
    started_at: datetime | None
    ended_at: datetime | None
    end_reason: str | None
    facts: list[FactOut]


class WebSessionOut(BaseModel):
    token: str
    expires_in: int


class FieldCell(BaseModel):
    value: Any | None  # None unless the owner's words back it up
    confirmed: bool
    display: str  # what the table shows; "Not confirmed" when unknown
    transcript_offset: int | None = None
    quote: str | None = None


class ComparisonRow(BaseModel):
    pg_id: UUID
    pg_name: str
    area_name: str
    call_id: UUID
    call_status: str
    provider: str = "web"  # "sample" for a pre-recorded demo call
    facts_checked: bool  # False until the transcript check has run
    fields: dict[str, FieldCell]


class ComparisonOut(BaseModel):
    plan_id: UUID
    field_order: list[str]
    rows: list[ComparisonRow]
