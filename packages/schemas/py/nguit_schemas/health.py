from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    service: str
    database: Literal["up", "down", "not_configured"]
    calling_enabled: bool
