"""When the owner MAY want the calls to stop, the code makes the agent ask, and acts on the answer.

A clear stop opts out at once (tests in test_session.py). These tests cover the in-between cases,
where a wrong guess either way would be a mistake: ignoring a stop, or opting a PG out for
every mover on a misunderstanding.
"""

import pytest
from fakes import FakeBackend
from nguit_tools.call_gate import pg_is_callable
from test_session import DISCLOSURE, end_call, fact, run
from voice_gateway.live import InTranscript, OutTranscript, TurnComplete
from voice_gateway.prompt import CONFIRM_STOP_KICK, OPENING_KICK

SIGNAL = "Please don't call me before eight in the morning"


def opening():
    return [OutTranscript(DISCLOSURE), TurnComplete()]


def owner_turn(text):
    """The owner says something and the model finishes its turn."""
    return [InTranscript(text), TurnComplete()]


def agent_turn(text="Would you like me to stop calling you?"):
    """The model's own turn ends. The owner said nothing in it."""
    return [OutTranscript(text), TurnComplete()]


def questions_asked(backend):
    return backend.texts.count(CONFIRM_STOP_KICK)


async def test_an_ambiguous_signal_makes_the_agent_ask_and_a_no_carries_on(make_call, conn):
    c = make_call()
    backend = FakeBackend(
        *opening(),
        *owner_turn(SIGNAL),
        *agent_turn(),
        *owner_turn("No, that's fine, go ahead"),
        fact("rent", "12000"),
        end_call(),
    )
    session, _ = await run(c.call_id, backend)
    assert backend.texts == [OPENING_KICK, CONFIRM_STOP_KICK]
    assert session.result == ("completed", "agent_ended")
    assert pg_is_callable(conn, c.pg_id)  # nobody was opted out


async def test_a_yes_to_the_question_opts_the_pg_out(make_call, conn):
    c = make_call()
    backend = FakeBackend(
        *opening(), *owner_turn(SIGNAL), *agent_turn(), *owner_turn("Yes please"), fact("rent", "9")
    )
    session, transport = await run(c.call_id, backend)
    assert session.result == ("opted_out", "confirmed_stop")
    assert not pg_is_callable(conn, c.pg_id)
    assert (
        conn.execute("SELECT 1 FROM call_facts WHERE call_id=%s", (c.call_id,)).fetchone() is None
    )
    assert transport.json[-1]["reason"] == "confirmed_stop"


async def test_the_agents_own_turn_does_not_count_as_the_answer(make_call):
    """After the question is asked, the model's turn ends with no owner speech. Not an answer."""
    c = make_call()
    backend = FakeBackend(
        *opening(),
        *owner_turn(SIGNAL),
        TurnComplete(),  # the model finishes its turn, the owner has said nothing
        TurnComplete(),
        *owner_turn("Yeah, please do"),
    )
    session, _ = await run(c.call_id, backend)
    assert session.result == ("opted_out", "confirmed_stop")


async def test_an_unclear_answer_carries_on_without_opting_out(make_call, conn):
    c = make_call()
    backend = FakeBackend(
        *opening(),
        *owner_turn(SIGNAL),
        *agent_turn(),
        *owner_turn("Hmm, the rent is twelve thousand"),
        end_call(),
    )
    session, _ = await run(c.call_id, backend)
    assert session.result == ("completed", "agent_ended")
    assert pg_is_callable(conn, c.pg_id)


async def test_an_owner_who_keeps_sounding_annoyed_is_treated_as_a_stop(make_call, conn):
    """Asked twice and said no both times, yet a third signal: stop asking, stop calling."""
    c = make_call()
    backend = FakeBackend(
        *opening(),
        *owner_turn("I'm tired of these calls"),
        *agent_turn(),
        *owner_turn("No"),
        *owner_turn("Honestly this is irritating"),
        *agent_turn(),
        *owner_turn("No"),
        *owner_turn("I'm done, I said it already"),
    )
    session, _ = await run(c.call_id, backend)
    assert questions_asked(backend) == 2  # never asked a third time
    assert session.result == ("opted_out", "repeated_signals")
    assert not pg_is_callable(conn, c.pg_id)


async def test_ordinary_talk_never_makes_the_agent_ask(make_call, conn):
    c = make_call()
    backend = FakeBackend(
        *opening(),
        *owner_turn("Rent is twelve thousand and the deposit is twenty"),
        *owner_turn("Don't worry about the deposit, it is refundable"),
        *owner_turn("No smoking and no alcohol"),
        end_call(),
    )
    session, _ = await run(c.call_id, backend)
    assert questions_asked(backend) == 0
    assert session.result == ("completed", "agent_ended")
    assert pg_is_callable(conn, c.pg_id)


async def test_a_clear_stop_in_the_answer_is_still_immediate(make_call, conn):
    c = make_call()
    backend = FakeBackend(
        *opening(),
        *owner_turn(SIGNAL),
        *agent_turn(),
        InTranscript("Yes, stop calling me"),
    )
    session, _ = await run(c.call_id, backend)
    assert session.result == ("opted_out", "stop_phrase")


# -- "end this call" is not an opt-out -------------------------------------------------------------
@pytest.mark.parametrize(
    "said", ["I have to go now", "End this call", "Okay, bye", "I need to leave"]
)
async def test_ending_the_call_does_not_opt_the_pg_out(make_call, conn, said):
    c = make_call()
    backend = FakeBackend(*opening(), InTranscript(said), fact("rent", "12000"))
    session, transport = await run(c.call_id, backend)
    assert session.result == ("ended_by_owner", "owner_asked_to_end")
    assert pg_is_callable(conn, c.pg_id)  # the PG can still be called by other movers
    assert (
        conn.execute("SELECT 1 FROM call_facts WHERE call_id=%s", (c.call_id,)).fetchone() is None
    )
    assert transport.json[-1]["status"] == "ended_by_owner"


# -- the optional classifier -----------------------------------------------------------------------
class Classifier:
    def __init__(self, says=True, fail=False):
        self.says, self.fail, self.seen = says, fail, []

    async def means_stop(self, text):
        self.seen.append(text)
        if self.fail:
            raise RuntimeError("model down")
        return self.says


async def test_a_classifier_can_make_the_agent_ask_about_phrasing_no_pattern_knows(make_call):
    c = make_call()
    odd = "Do me a favour and lose this number"  # no pattern matches this
    classifier = Classifier(says=True)
    backend = FakeBackend(*opening(), *owner_turn(odd), *agent_turn(), *owner_turn("Yes"))
    session, _ = await run(c.call_id, backend, stop_classifier=classifier)
    assert classifier.seen == [odd]
    assert session.result == ("opted_out", "confirmed_stop")


async def test_a_classifier_alone_never_opts_out_without_the_owner_saying_yes(make_call, conn):
    c = make_call()
    backend = FakeBackend(
        *opening(),
        *owner_turn("Rent is twelve thousand"),
        *agent_turn(),
        *owner_turn("No"),
        end_call(),
    )
    await run(c.call_id, backend, stop_classifier=Classifier(says=True))
    assert pg_is_callable(conn, c.pg_id)


async def test_a_failing_classifier_never_breaks_the_call(make_call):
    c = make_call()
    backend = FakeBackend(*opening(), *owner_turn("Rent is 12000"), end_call())
    session, _ = await run(c.call_id, backend, stop_classifier=Classifier(fail=True))
    assert session.result == ("completed", "agent_ended")


async def test_the_classifier_is_not_asked_when_a_pattern_already_matched(make_call):
    c = make_call()
    classifier = Classifier(says=False)
    backend = FakeBackend(
        *opening(), *owner_turn(SIGNAL), *agent_turn(), *owner_turn("No"), end_call()
    )
    await run(c.call_id, backend, stop_classifier=classifier)
    assert SIGNAL not in classifier.seen  # the patterns already decided to ask
