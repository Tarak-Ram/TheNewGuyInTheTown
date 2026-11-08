"""Runs the extraction eval in CI. A drop in quality fails the build."""

import json

from extraction_eval import CASES, TARGET, load_cases, run
from nguit_tools.call_gate import CALL_FIELDS
from nguit_tools.extractors import RuleExtractor


def test_eval_set_has_at_least_ten_transcripts():
    assert len(load_cases()) >= 10


def test_every_label_uses_a_real_field():
    for case in load_cases():
        assert set(case["expected"]) <= set(CALL_FIELDS), case["id"]


def test_eval_cases_include_the_hard_ones():
    ids = {c["id"] for c in load_cases()}
    assert {"hedged_rent", "yes_to_agent_statement", "owner_refuses"} <= ids
    assert any("injection" in i for i in ids)
    assert "synthetic" in json.loads(CASES.read_text(encoding="utf-8"))["about"].lower()


def test_rules_extractor_meets_the_prd_accuracy_target():
    report = run(RuleExtractor())
    assert report.accuracy >= TARGET, report
    assert report.recall >= TARGET, report


def test_rules_extractor_never_saves_a_wrong_value_as_confirmed():
    report = run(RuleExtractor())
    assert report.false_confirmations == [], report.false_confirmations
