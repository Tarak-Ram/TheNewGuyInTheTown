"""Structured JSON logs that cannot leak phone numbers, secrets or call-link tokens.

Cloud Logging reads one JSON object per line from stdout and understands `severity`.
Everything written through the root logger passes through `mask`, including the access
logs from uvicorn, whose URLs can carry one-time tokens in the query string.

What is removed:
  - phone numbers, in any common Indian format (10 digits, with or without +91, 91 or 0,
    with spaces or dashes). Only the last two digits stay, to help tell numbers apart;
  - long digit runs of 12 to 19 digits (Aadhaar and card numbers), which must never be asked
    for on a call and must never be logged;
  - `token=...` in URLs, and the value of any key that looks like a secret.
UUIDs are left alone, so a call id can always be followed from log to log.
"""

import json
import logging
import os
import re
import sys
from datetime import UTC, datetime

UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE
)
PHONE = re.compile(r"(?<![\w.])(?:\+?91[\s-]?|0)?(\d{5})[\s-]?(\d{5})(?![\w])")
LONG_NUMBER = re.compile(r"(?<![\w.])(?:\d[\s-]?){12,19}(?![\w])")
URL_TOKEN = re.compile(r"([?&](?:token|id_token|access_token|api_key|key)=)[^&\s\"']+", re.I)
BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)

SECRET_KEYS = {
    "authorization", "cookie", "set-cookie", "token", "id_token", "access_token", "password",
    "secret", "session", "api_key", "phone", "phone_encrypted", "phone_number", "mobile",
    "otp", "card", "aadhaar",
}  # fmt: skip

# Python logging attributes that are not our own fields.
_STANDARD = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "color_message",  # uvicorn adds a copy of the message with terminal colour codes
}


def _mask_plain(text: str) -> str:
    text = URL_TOKEN.sub(r"\1[redacted]", text)
    text = BEARER.sub(r"\1[redacted]", text)
    # Phones first: with a country code they have 12 digits, like an Aadhaar number.
    text = PHONE.sub(lambda m: f"[phone ***{m.group(2)[-2:]}]", text)
    return LONG_NUMBER.sub("[number redacted]", text)


def mask(text: str) -> str:
    """Hides phone numbers and secrets in free text. Safe to call on any string."""
    pieces = UUID.split(text)
    ids = UUID.findall(text)
    out = []
    for i, piece in enumerate(pieces):
        out.append(_mask_plain(piece))
        if i < len(ids):
            out.append(ids[i])  # keep ids intact so logs can still be correlated
    return "".join(out)


def clean(value, key: str = ""):
    """Recursively masks strings and redacts the value of secret-looking keys."""
    if key.lower() in SECRET_KEYS:
        return "[redacted]"
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, dict):
        return {str(k): clean(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [clean(v) for v in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return mask(str(value))


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str):
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "severity": record.levelname,  # DEBUG, INFO, WARNING, ERROR, CRITICAL
            "message": mask(record.getMessage()),
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "service": self.service,
            "logger": record.name,
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                payload[key] = clean(value, key)
        if record.exc_info:
            payload["exception"] = mask(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(service: str) -> None:
    """Sends every log line, including uvicorn's, through the JSON formatter. Safe to repeat."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    handler._nguit = True  # type: ignore[attr-defined]

    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not getattr(h, "_nguit", False)]
    root.addHandler(handler)
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []  # uvicorn's own formatter would bypass the masking
        lg.propagate = True
