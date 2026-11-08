"""Stop requests the way real people say them.

These phrases were written from how owners actually talk, not from the detector's patterns.
The first version of the detector, tested only on phrases written alongside it, caught 54% of
a list like this one. Add to these lists whenever a real call shows a phrasing that was missed.

A wrong "stop" is not free: ending a call opts the PG out for every mover. So the second list
holds ordinary talk that must NOT end a call.
"""

import pytest
from voice_gateway.stopwords import (
    answer_to_stop_question,
    is_end_request,
    is_stop_request,
    needs_stop_confirmation,
)

MUST_STOP = [
    # asking for no more calls
    "I don't want any more calls",
    "I don't want these calls",
    "I do not want to receive calls like this",
    "No more calls please",
    "No more calls",
    "Please no more calls",
    "I don't wish to get any calls",
    "I do not wish to receive these calls",
    # stop / quit / enough
    "Stop calling",
    "Stop calling me",
    "Please stop calling this number",
    "Quit calling me",
    "Enough, stop calling me",
    "I told you before, stop",
    "Stop it",
    "Just stop",
    "Stop.",
    "Stop, please stop",
    "Please stop",
    "Stop bothering me",
    "Stop disturbing me",
    "Why do you keep calling me? Stop",
    # don't call / never call
    "Don't call me",
    "Don't call me again",
    "Don't call this number again",
    "Do not call me again",
    "Never call me again",
    "Please don't ring this number again",
    "I'm busy, don't call me again",
    "Don't call here anymore",
    "Do not contact me",
    "Don't message or call me",
    # take me off / remove / delete
    "Take me off your calling list",
    "Take my number off your list",
    "Please remove my number",
    "Remove my number from your list",
    "Who gave you my number? Remove it",
    "Delete my details",
    "Erase my number from your database",
    "Remove me from your database",
    # bother / disturb / harass / spam / block
    "Please do not disturb me again",
    "Don't disturb me",
    "Do not bother us",
    "This is harassment, stop",
    "You are harassing me",
    "I am reporting this as spam",
    "This is spam",
    "I am going to block this number",
    "Block this number",
    # robots and AI
    "I am not comfortable talking to a robot",
    "I don't want to speak with a machine",
    "I don't want to talk to an AI",
    "No AI calls please",
    "I hate these robot calls",
    "I don't like talking to a bot",
    # leaving
    "Leave me alone",
    "Hang up now",
    "Please hang up",
    "Wrong number, don't call again",
]

MUST_CONTINUE = [
    "Rent is twelve thousand",
    "Rent is 12000 and deposit is 24000",
    "The PG is near the bus stop",
    "We stop serving dinner at nine",
    "You can stop by tomorrow to see the room",
    "Call me back tomorrow",
    "Not now, I am busy, call later",
    "Can you call me after lunch?",
    "Yes, this is a good time",
    "Please hold on a moment",
    "Do you want the deposit details?",
    "I don't know the exact rent",
    "We don't allow smoking",
    "Don't worry, there is no deposit",
    "No problem, go ahead",
    "No food on Sundays",
    "There are no more rooms on the first floor",
    "No more vacancies in the double sharing",
    "You can call me on Monday",
    "Don't forget to call me tomorrow",
    "Please don't call after nine pm",
    "Please don't forget to bring your ID",
    "I can't talk for long",
    "I am not sure about the notice period",
    "He is not interested in food, he eats outside",
    "We have not blocked any rooms",
    "Quite interested, tell me more",
    "Thank you for calling",
    "Hello, who is this?",
    "Okay, what do you want to know?",
]


@pytest.mark.parametrize("text", MUST_STOP)
def test_every_way_of_asking_to_stop_ends_the_call(text):
    assert is_stop_request(text), f"not caught: {text!r}"


@pytest.mark.parametrize("text", MUST_CONTINUE)
def test_ordinary_talk_does_not_end_the_call(text):
    assert not is_stop_request(text), f"wrongly ended the call: {text!r}"


def test_the_lists_are_big_enough_to_mean_something():
    assert len(MUST_STOP) >= 55 and len(MUST_CONTINUE) >= 30


def test_a_stop_hidden_inside_a_longer_answer_is_still_caught():
    long_answer = "Yes the rent is 12000 per month but honestly please stop calling me about this"
    assert is_stop_request(long_answer)


def test_shouting_and_odd_spacing_do_not_hide_a_stop():
    assert is_stop_request("STOP   CALLING   ME!!!")
    assert is_stop_request("stop... calling... me")


# -- possible stops: the agent asks, nothing is decided by a pattern --------------------------
# Each of these has a reading where the owner just wants less contact, not an opt-out for ever.
ASK_NOT_OPT_OUT = [
    "I am not interested",
    "Not interested, thanks",
    "We are not interested in this",
    "No thanks, not interested",
    "I am not interested in selling this property",
    "Please don't call me before eight in the morning",
    "Please don't call after nine, I sleep early",
    "I'm tired of these calls",
    "Do not call me back please",
]

# Phrasings found on fresh holdouts. Every one is a real way of asking to stop, and none may
# slip through unnoticed: each must at least make the agent ask, and clear ones end the call.
HOLDOUT_STOPS = [
    "Stop these calls",
    "I want you to stop",
    "I request you not to call again",
    "Please, no more",
    "I won't talk to a recording",
    "I'm going to file a complaint",
    "I do not consent to these calls",
    "You people keep disturbing me",
    "Please leave us alone",
    "I am not available for such calls",
    "I am telling you for the last time, do not call",
    "How many times should I say no? Don't call",
    "I don't need any calls from you",
    "I will call the police if you call again",
    "Who are you? I never agreed to these calls",
    "I have no interest, please don't call",
    "Can you please not call me again",
    "I'm blocking your number",
    "I said no, don't ever call",
    "Madam, I humbly request you to stop calling me",
    "Please do the needful and delete my number",
    "Arre baba, enough of this, no more calls",
    "I'm not going to answer any more of these, so stop",
    "Please don't call on this number anymore",
    "My number is on the do not disturb list, why are you calling",
    "I'm tired of these calls. Stop them.",
    "Sir, I am requesting once more, no calls",
    "I don't want to hear from you people again",
    "Please cancel all calls to this number",
    "I withdraw whatever permission I gave",
    "I don't want your calls",
    "I'm reporting this number",
    "Go away and don't call",
    "Don't contact this number again",
    "Look, I'm not interested in any of this, please remove me",
    "We will not take any calls from you, kindly stop",
    "Take my details out of your list",
    "Okay I'm done with this, stop calling",
    "You have been calling daily, it is irritating, stop it",
    "Please cancel all calls to this number",
    "I have no wish to continue, please don't call back",
]

# Ordinary talk. None of it may be treated as a clear stop.
NEVER_AN_OPT_OUT = [
    "I am not interested in selling this property",
    "Please don't call me before eight in the morning",
    "Please don't call after nine, I sleep early",
    "Can you not call me during lunch?",
    "Don't call the landline, use my mobile",
    "I can't stop now, I am cooking, can you wait?",
    "You can stop by on Saturday",
    "They stopped the bus service last year",
    "The owner does not want any pets",
    "My brother is not interested in this room, but I am",
]

# Ordinary talk that should not even make the agent ask.
NO_QUESTION = [
    "Rent is twelve thousand",
    "We stop serving dinner at nine",
    "The PG is near the bus stop",
    "Call me back tomorrow",
    "I'm busy right now, can you call me tomorrow evening?",
    "No smoking, no drinking, and no loud music after ten",
    "Don't worry about the deposit",
    "Don't forget to call me tomorrow",
    "Please do not park in front of the gate",
    "No more bookings for December",
    "Call the warden if you need anything",
    "I don't know the exact rent",
    "We don't allow smoking",
    "Yes, this is a good time",
    "It's fine, go on, what else do you want to know?",
    "I'm not available now, call me at six",
]


@pytest.mark.parametrize("text", ASK_NOT_OPT_OUT)
def test_ambiguous_phrases_make_the_agent_ask_and_never_opt_out_by_themselves(text):
    assert needs_stop_confirmation(text), f"the agent should ask: {text!r}"
    assert not is_stop_request(text), f"must not opt out without asking: {text!r}"


@pytest.mark.parametrize("text", sorted(set(HOLDOUT_STOPS)))
def test_no_real_way_of_asking_to_stop_goes_unnoticed(text):
    noticed = is_stop_request(text) or needs_stop_confirmation(text) or is_end_request(text)
    assert noticed, f"missed completely: {text!r}"


@pytest.mark.parametrize("text", NEVER_AN_OPT_OUT)
def test_ordinary_talk_never_opts_a_pg_out_by_itself(text):
    assert not is_stop_request(text), f"wrongly treated as a clear stop: {text!r}"


@pytest.mark.parametrize("text", NO_QUESTION)
def test_ordinary_talk_does_not_make_the_agent_ask(text):
    assert not needs_stop_confirmation(text) and not is_stop_request(text), text


@pytest.mark.parametrize(
    "text", ["End this call", "Cut the call", "I have to go now", "I need to leave"]
)
def test_ending_the_call_is_not_an_opt_out(text):
    assert is_end_request(text) and not is_stop_request(text)


def test_a_clear_stop_beats_an_end_request():
    assert is_stop_request("Stop calling me and end this call")
    assert not is_end_request("Stop calling me and end this call")


@pytest.mark.parametrize("text", ["Yes", "Yeah please", "Yes, stop", "Sure", "Stop", "Correct"])
def test_a_yes_to_the_question_is_a_yes(text):
    assert answer_to_stop_question(text) == "yes"


@pytest.mark.parametrize(
    "text",
    [
        "No",
        "No, it's fine",
        "Nope, carry on",
        "Not really",
        "No no, go ahead",
        "Never mind, continue",
    ],
)
def test_a_no_to_the_question_is_a_no(text):
    assert answer_to_stop_question(text) == "no"


def test_no_stop_beats_yes():
    assert answer_to_stop_question("No, don't stop") == "no"


def test_a_rambling_answer_is_unclear_not_a_yes():
    assert answer_to_stop_question("Hmm, the rent is twelve thousand") == "unclear"
