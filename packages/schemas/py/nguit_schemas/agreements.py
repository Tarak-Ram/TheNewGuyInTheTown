from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# Shown with every result. Keep the wording plain and keep it on every response.
DISCLAIMER = (
    "This is not legal advice. It is an automated reading of your agreement to help you "
    "ask better questions. It can miss things or get things wrong. For a serious issue, "
    "or before you sign or pay, speak to a lawyer."
)

ALLOWED_TYPES = ("application/pdf", "image/jpeg", "image/png")
MAX_PAGES = 20
MAX_BYTES = 15 * 1024 * 1024


class AgreementCreate(BaseModel):
    plan_id: UUID
    filename: str = Field(min_length=1, max_length=120)
    content_type: str
    size_bytes: int = Field(gt=0)
    pg_id: UUID | None = None


class AgreementCreated(BaseModel):
    id: UUID
    upload_url: str  # short-lived, single-use
    expires_in: int
    max_bytes: int
    allowed_types: list[str]


class AgreementStatus(BaseModel):
    id: UUID
    status: Literal["awaiting_upload", "uploaded", "analyzing", "done", "unreadable", "failed"]
    message: str | None = None


class RiskOut(BaseModel):
    type: str
    severity: Literal["high", "medium", "low"]
    page: int | None
    quote: str  # the exact words from the agreement
    quote_translation: str | None = None  # English meaning, when the clause is not in English
    explanation: str
    question_to_ask: str
    source: Literal["model", "rules"] = "model"


class ReportOut(BaseModel):
    id: UUID
    status: str
    message: str | None = None
    disclaimer: str = DISCLAIMER  # on every result, whatever the status
    filename: str | None = None
    pages: int | None = None
    text_source: str | None = None
    language: str | None = None
    injection_detected: bool = False
    warnings: list[str] = []
    risk_counts: dict[str, int] = {}
    risks: list[RiskOut] = []
    created_at: datetime | None = None
