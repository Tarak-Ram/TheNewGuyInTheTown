"""Shared health-check app factory used by api, voice-gateway and worker."""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from nguit_schemas import HealthResponse, ReadyResponse

from nguit_tools.safe_logging import configure_logging


def calling_enabled() -> bool:
    # Default is off. Only the literal string "true" turns calling on.
    return os.environ.get("CALLING_ENABLED", "false").strip().lower() == "true"


def database_status() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return "not_configured"
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return "up"
    except Exception:
        return "down"


def create_app(service: str, title: str, lifespan=None) -> FastAPI:
    # Right away, so uvicorn's first lines ("Started server process") are JSON too.
    configure_logging(service)

    @asynccontextmanager
    async def combined(app: FastAPI):
        # Runs after uvicorn has set up its own logging, so ours wins: one JSON object per
        # line, with phone numbers and secrets masked.
        configure_logging(service)
        if lifespan is None:
            yield
        else:
            async with lifespan(app):
                yield

    app = FastAPI(title=title, lifespan=combined)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service=service)

    @app.get("/health/ready", response_model=ReadyResponse)
    def ready(response: Response) -> ReadyResponse:
        db = database_status()
        ok = db != "down"
        if not ok:
            response.status_code = 503
        return ReadyResponse(
            status="ready" if ok else "not_ready",
            service=service,
            database=db,
            calling_enabled=calling_enabled(),
        )

    return app
