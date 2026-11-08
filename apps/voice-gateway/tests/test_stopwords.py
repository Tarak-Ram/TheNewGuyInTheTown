import pytest
from voice_gateway.stopwords import is_stop_request

STOP = [
    "Stop calling me",
    "please stop",
    "Stop.",
    "stop",
    "Don't call me again",
    "do not call this number",
    "Take my number off your list",
    "remove my number",
    "remove me from your list",
    "Leave me alone",
    "I don't want to talk to a robot",
    "I don't want an AI",
    "no more AI calls",
    "this is a wrong number",
    "please hang up",
    "unsubscribe me",
    "STOP CALLING",
    "Hey, stop this",
]

NOT_STOP = [
    "The PG is near the bus stop",
    "We can stop by the gate at six",
    "Rent is twelve thousand",
    "Yes this is a good time",
    "Food is included, breakfast and dinner",
    "The deposit is twenty thousand rupees",
    "Notice period is one month",
    "Hello",
    "I have a double sharing room available from December",
    "Can you call me tomorrow?",
]


@pytest.mark.parametrize("text", STOP)
def test_stop_phrases_are_detected(text):
    assert is_stop_request(text)


@pytest.mark.parametrize("text", NOT_STOP)
def test_normal_speech_is_not_a_stop(text):
    assert not is_stop_request(text)
