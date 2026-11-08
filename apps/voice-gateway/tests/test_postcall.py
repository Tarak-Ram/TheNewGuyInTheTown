"""A whole call, end to end with a scripted model: speak, hang up, facts appear in the table."""

from fakes import FakeBackend
from test_session import DISCLOSURE, end_call, fact, run
from voice_gateway.live import InTranscript, OutTranscript, TurnComplete
from voice_gateway.postcall import extract_after_call

from conftest import sign_in  # noqa: F401  (fixtures come from the root conftest)


async def test_call_to_comparison_table(client, make_call, conn):
    c = make_call()
    backend = FakeBackend(
        OutTranscript(DISCLOSURE),
        TurnComplete(),
        InTranscript("The rent is twelve thousand per month and deposit is 24000."),
        TurnComplete(),
        fact("rent", "12000"),  # the model's live note
        fact("deposit", "99999", id="bad"),  # a wrong live note: the transcript says 24000
        end_call(),
    )
    session, _ = await run(c.call_id, backend)
    assert session.result == ("completed", "agent_ended")

    # Until the transcript check has run, nothing is shown as confirmed.
    before = client.get(f"/v1/plans/{c.plan_id}/comparison", headers=c.headers).json()
    assert before["rows"][0]["fields"]["rent"]["display"] == "Not confirmed"

    assert await extract_after_call(c.call_id) is True

    row = client.get(f"/v1/plans/{c.plan_id}/comparison", headers=c.headers).json()["rows"][0]
    assert row["facts_checked"] is True
    assert row["fields"]["rent"]["display"] == "Rs 12,000"
    assert row["fields"]["deposit"]["display"] == "Rs 24,000"  # not the model's 99999
    assert row["fields"]["food"]["display"] == "Not confirmed"


async def test_an_opted_out_call_keeps_only_what_was_said_before_the_stop(client, make_call):
    c = make_call()
    backend = FakeBackend(
        OutTranscript(DISCLOSURE),
        TurnComplete(),
        InTranscript("Rent is 9000 per month."),
        TurnComplete(),
        InTranscript("Actually please stop calling me."),
    )
    session, _ = await run(c.call_id, backend)
    assert session.result == ("opted_out", "stop_phrase")
    await extract_after_call(c.call_id)
    row = client.get(f"/v1/plans/{c.plan_id}/comparison", headers=c.headers).json()["rows"][0]
    assert row["call_status"] == "opted_out"
    assert row["fields"]["rent"]["display"] == "Rs 9,000"
    assert row["fields"]["deposit"]["display"] == "Not confirmed"


async def test_extraction_failure_never_breaks_the_call_result(make_call, monkeypatch):
    c = make_call()
    await run(c.call_id, FakeBackend(OutTranscript(DISCLOSURE), TurnComplete(), end_call()))
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    assert await extract_after_call(c.call_id) is False  # logged, not raised
