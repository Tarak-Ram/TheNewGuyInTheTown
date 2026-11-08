"""Runs the stop-request eval in CI.

The floors below are regression guards on a set the patterns were tuned on, NOT a promise
about real calls. The never-tuned number is the honest one, and it is low without a model.
"""

from stop_eval import UNSEEN, load, run


class FakeClassifier:
    """Says "stop" for phrases containing a given word, so we can test how the eval uses it."""

    model = "fake"

    def __init__(self, word):
        self.word = word

    async def means_stop(self, text):
        return self.word in text.lower()


def test_the_eval_set_is_big_enough_and_has_a_never_tuned_part():
    data = load()
    assert len(data["stops"]) >= 150 and len(data["normal"]) >= 80
    assert any(c["source"] == UNSEEN for c in data["stops"])
    assert "never" in data["about"].lower() or "not" in data["about"].lower()


def test_ordinary_talk_never_opts_a_pg_out():
    assert run().wrong_opt_outs == []


def test_most_stop_requests_are_noticed_and_the_floor_does_not_drop():
    report = run()
    assert report.recall() >= 0.90, report.missed
    # Phrasing the patterns have not been tuned on. Do not raise this number by tuning on the
    # set; raise it with a model (python evals/stop_eval.py --classifier model).
    assert report.recall(UNSEEN) >= 0.50


def test_the_agent_does_not_ask_needlessly_too_often():
    report = run()
    assert len(report.needless_asks) <= 0.10 * report.normal, report.needless_asks


def test_a_classifier_can_only_add_questions_never_opt_outs():
    baseline = run()
    helped = run(FakeClassifier("number"))
    assert helped.recall() >= baseline.recall()
    assert helped.classifier_rescued > 0
    assert helped.wrong_opt_outs == []  # a classifier cannot create a wrong opt-out
