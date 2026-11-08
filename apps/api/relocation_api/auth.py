"""Google sign-in and our own short session tokens.

The browser gets a Google ID token, we verify it server-side, then issue our own
signed session token. Every request is tied to a user id taken from that token.
"""

import logging
import os
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException
from nguit_schemas import GoogleSignIn, SessionResponse, UserOut
from pydantic import BaseModel

from relocation_api.db import get_conn
from relocation_api.demo import DEMO_USER_EMAIL, DEMO_USER_SUB, demo_mode

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["auth"])

SESSION_HOURS = 12
_ephemeral_secret = secrets.token_urlsafe(32)


class GoogleClaims(BaseModel):
    sub: str
    email: str


def _session_secret() -> str:
    secret = os.environ.get("SESSION_SECRET")
    if secret:
        return secret
    # Local dev only: a random per-process secret, so sessions reset on restart.
    log.warning("SESSION_SECRET is not set; using a temporary secret")
    return _ephemeral_secret


def verify_google_id_token(token: str) -> GoogleClaims:
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    if not client_id:
        raise HTTPException(503, "Google sign-in is not configured")
    try:
        info = id_token.verify_oauth2_token(token, g_requests.Request(), client_id)
    except ValueError:
        raise HTTPException(401, "Invalid Google token") from None
    if not info.get("email_verified"):
        raise HTTPException(401, "Google email is not verified")
    return GoogleClaims(sub=info["sub"], email=info["email"])


def get_token_verifier() -> Callable[[str], GoogleClaims]:
    return verify_google_id_token


def issue_session_token(user_id: UUID) -> str:
    exp = datetime.now(UTC) + timedelta(hours=SESSION_HOURS)
    return jwt.encode({"sub": str(user_id), "exp": exp}, _session_secret(), algorithm="HS256")


def current_user(
    authorization: str | None = Header(default=None),
    conn: psycopg.Connection = Depends(get_conn),
) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sign in required")
    try:
        payload = jwt.decode(authorization[7:], _session_secret(), algorithms=["HS256"])
        user_id = UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "Invalid or expired session") from None
    user = conn.execute(
        "SELECT id, email, language FROM users WHERE id = %s AND deleted_at IS NULL", (user_id,)
    ).fetchone()
    if user is None:
        raise HTTPException(401, "Invalid or expired session")
    return user


@router.post("/auth/google", response_model=SessionResponse)
def sign_in(
    body: GoogleSignIn,
    conn: psycopg.Connection = Depends(get_conn),
    verifier: Callable[[str], GoogleClaims] = Depends(get_token_verifier),
) -> SessionResponse:
    claims = verifier(body.id_token)
    user = conn.execute(
        """
        INSERT INTO users (google_sub, email) VALUES (%s, %s)
        ON CONFLICT (google_sub) DO UPDATE SET email = EXCLUDED.email
        WHERE users.deleted_at IS NULL
        RETURNING id, email, language
        """,
        (claims.sub, claims.email),
    ).fetchone()
    if user is None:  # the account was deleted; it must not be silently revived
        raise HTTPException(403, "This account has been deleted")
    conn.execute(
        "INSERT INTO audit_events (actor, action, object_type, object_id) VALUES (%s, %s, %s, %s)",
        (str(user["id"]), "sign_in", "user", str(user["id"])),
    )
    return SessionResponse(access_token=issue_session_token(user["id"]), user=UserOut(**user))


@router.post("/auth/demo", response_model=SessionResponse)
def demo_sign_in(conn: psycopg.Connection = Depends(get_conn)) -> SessionResponse:
    """Signs in the one fixed demo user. Does not exist unless DEMO_MODE=true."""
    if not demo_mode():
        raise HTTPException(404, "Not found")
    user = conn.execute(
        """
        INSERT INTO users (google_sub, email) VALUES (%s, %s)
        ON CONFLICT (google_sub) DO UPDATE SET deleted_at = NULL
        RETURNING id, email, language
        """,
        (DEMO_USER_SUB, DEMO_USER_EMAIL),
    ).fetchone()
    conn.execute(
        "INSERT INTO audit_events (actor, action, object_type, object_id) VALUES (%s, %s, %s, %s)",
        (str(user["id"]), "demo_sign_in", "user", str(user["id"])),
    )
    return SessionResponse(access_token=issue_session_token(user["id"]), user=UserOut(**user))


@router.get("/me", response_model=UserOut)
def me(user: dict = Depends(current_user)) -> UserOut:
    return UserOut(**user)
