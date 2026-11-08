"""Short-lived, single-use tokens that let a browser open the voice gateway for one call.

The API mints the token after its checks. The gateway verifies the signature, re-runs the
checks, then marks the token used in the database so it cannot be replayed.
"""

import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

AUDIENCE = "voice-gateway"
TTL_SECONDS = 120


class TokenError(Exception):
    pass


def _secret() -> str:
    secret = os.environ.get("SESSION_SECRET")
    if not secret:
        raise TokenError("SESSION_SECRET is not set")
    return secret


def hash_jti(jti: str) -> str:
    return hashlib.sha256(jti.encode()).hexdigest()


def mint(call_id: UUID) -> tuple[str, str]:
    """Returns (token, jti). Store hash_jti(jti) on the call row."""
    jti = secrets.token_urlsafe(24)
    exp = datetime.now(UTC) + timedelta(seconds=TTL_SECONDS)
    token = jwt.encode(
        {"sub": str(call_id), "jti": jti, "aud": AUDIENCE, "exp": exp},
        _secret(),
        algorithm="HS256",
    )
    return token, jti


def verify(token: str, call_id: UUID) -> str:
    """Returns the jti if the token is valid for exactly this call."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=["HS256"], audience=AUDIENCE)
    except jwt.PyJWTError as exc:
        raise TokenError("invalid or expired token") from exc
    if payload.get("sub") != str(call_id) or not payload.get("jti"):
        raise TokenError("token is for a different call")
    return payload["jti"]
