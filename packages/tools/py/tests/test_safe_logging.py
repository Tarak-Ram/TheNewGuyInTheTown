import io
import json
import logging

import pytest
from nguit_tools.safe_logging import JsonFormatter, clean, configure_logging, mask

UUID_CALL = "11111111-2222-3333-4444-555555555555"


@pytest.mark.parametrize(
    "text",
    [
        "9876543210",
        "+91 98765 43210",
        "+91-98765-43210",
        "91 9876543210",
        "098765 43210",
        "98765-43210",
        "call 9876543210 now",
        "phone=9876543210",
        "(9876543210)",
        "+91 00000 00099",  # the fake sample numbers are masked too
    ],
)
def test_phone_numbers_are_masked_in_every_common_format(text):
    out = mask(text)
    assert "98765" not in out and "00000" not in out
    assert "[phone ***" in out


def test_only_the_last_two_digits_of_a_phone_survive():
    assert mask("Owner phone is +91 98765 43210.") == "Owner phone is [phone ***10]."


@pytest.mark.parametrize(
    "text",
    [
        "Rent is 12000 per month",
        "deposit 240000",
        "Rs 1,20,000",
        "page 12 of 20",
        "at 2026-11-09T10:15:00",
        "elapsed 1234567 ms",
        "version 1.2.3456",
    ],
)
def test_ordinary_numbers_are_left_alone(text):
    assert mask(text) == text


def test_aadhaar_and_card_length_numbers_are_removed():
    assert "[number redacted]" in mask("aadhaar 1234 5678 9012")
    assert "[number redacted]" in mask("card 4111-1111-1111-1111")
    assert "1234" not in mask("aadhaar 1234 5678 9012")


def test_uuids_survive_even_when_they_end_in_twelve_digits():
    assert mask(f"call {UUID_CALL} ended") == f"call {UUID_CALL} ended"


def test_tokens_in_urls_are_hidden():
    line = 'PUT /v1/agreements/abc/file?token=eyJhbGciOi.secret.sig HTTP/1.1" 200'
    out = mask(line)
    assert "eyJhbGciOi" not in out and "token=[redacted]" in out
    assert mask("ws /v1/calls/x/web?token=abc123&x=1").count("abc123") == 0


def test_bearer_tokens_are_hidden():
    assert "abcdef" not in mask("Authorization: Bearer abcdef.ghijk.lmnop")


def test_secret_looking_keys_are_redacted_whatever_the_value():
    out = clean({"authorization": "Bearer x", "Phone": "9876543210", "ok": "fine", "n": 3})
    assert out == {"authorization": "[redacted]", "Phone": "[redacted]", "ok": "fine", "n": 3}


def test_nested_values_are_cleaned():
    out = clean({"call": {"owner": "call 9876543210", "ids": [UUID_CALL, "98765 43210"]}})
    assert "98765" not in json.dumps(out) and UUID_CALL in json.dumps(out)


def make_logger(service="api"):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter(service))
    log = logging.getLogger(f"test.{id(stream)}")
    log.handlers, log.propagate = [handler], False
    log.setLevel(logging.DEBUG)
    return log, stream


def test_each_line_is_one_json_object_with_a_cloud_logging_severity():
    log, stream = make_logger("voice-gateway")
    log.warning(
        "owner said %s", "call me on 9876543210", extra={"event": "x", "call_id": UUID_CALL}
    )
    line = json.loads(stream.getvalue())
    assert line["severity"] == "WARNING" and line["service"] == "voice-gateway"
    assert line["event"] == "x" and line["call_id"] == UUID_CALL
    assert "98765" not in stream.getvalue()


def test_extra_fields_with_secrets_are_redacted_in_the_output():
    log, stream = make_logger()
    log.info("signed in", extra={"token": "abc", "phone": "9876543210", "user": "u1"})
    line = json.loads(stream.getvalue())
    assert line["token"] == "[redacted]" and line["phone"] == "[redacted]" and line["user"] == "u1"


def test_exceptions_are_logged_with_their_text_masked():
    log, stream = make_logger()
    try:
        raise ValueError("bad number 9876543210")
    except ValueError:
        log.exception("failed")
    line = json.loads(stream.getvalue())
    assert "98765" not in line["exception"] and "ValueError" in line["exception"]


def test_uvicorns_colour_codes_do_not_end_up_in_the_json():
    log, stream = make_logger()
    log.info("Uvicorn running", extra={"color_message": "Uvicorn \x1b[1mrunning\x1b[0m"})
    line = json.loads(stream.getvalue())
    assert "color_message" not in line and "\x1b" not in stream.getvalue()


def test_unserialisable_extras_do_not_break_logging():
    log, stream = make_logger()
    log.info("odd", extra={"thing": object()})
    assert json.loads(stream.getvalue())["message"] == "odd"


def test_configure_logging_is_repeatable_and_covers_uvicorn(capsys):
    configure_logging("api")
    configure_logging("api")
    root = logging.getLogger()
    assert sum(getattr(h, "_nguit", False) for h in root.handlers) == 1
    logging.getLogger("uvicorn.access").info('GET /x?token=secret123 "200"')
    out = capsys.readouterr().out
    assert "secret123" not in out and "token=[redacted]" in out
    assert json.loads(out.strip().splitlines()[-1])["severity"] == "INFO"
