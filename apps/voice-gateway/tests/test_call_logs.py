"""The structured log lines that dashboards and alerts depend on."""

import json
import logging

from fakes import FakeBackend
from test_session import DISCLOSURE, end_call, run
from voice_gateway.live import InTranscript, OutTranscript, TurnComplete


def events(caplog, name):
    return [r for r in caplog.records if getattr(r, "event", None) == name]


async def test_every_call_logs_one_outcome_line(make_call, caplog):
    c = make_call()
    with caplog.at_level(logging.INFO):
        await run(c.call_id, FakeBackend(OutTranscript(DISCLOSURE), TurnComplete(), end_call()))
    (line,) = events(caplog, "call_ended")
    assert line.status == "completed" and line.reason == "agent_ended"
    assert line.call_id == str(c.call_id) and line.disclosed is True
    assert line.duration_s >= 0


async def test_opt_outs_are_logged_for_the_spike_alert(make_call, caplog):
    c = make_call()
    with caplog.at_level(logging.INFO):
        await run(
            c.call_id,
            FakeBackend(
                OutTranscript(DISCLOSURE), TurnComplete(), InTranscript("Please stop calling me")
            ),
        )
    (opt,) = events(caplog, "owner_opt_out")
    assert opt.source == "stop_phrase" and opt.levelname == "WARNING"
    assert events(caplog, "call_ended")[0].status == "opted_out"


async def test_call_logs_contain_no_phone_numbers_even_if_the_owner_says_one(make_call, caplog):
    c = make_call()
    with caplog.at_level(logging.DEBUG):
        await run(
            c.call_id,
            FakeBackend(
                OutTranscript(DISCLOSURE),
                TurnComplete(),
                InTranscript("Call me on 98765 43210 please stop calling"),
            ),
        )
    from nguit_tools.safe_logging import JsonFormatter

    formatter = JsonFormatter("voice-gateway")
    rendered = "\n".join(formatter.format(r) for r in caplog.records)
    assert "98765" not in rendered and "43210" not in rendered
    for line in rendered.splitlines():
        json.loads(line)  # every line is valid JSON
