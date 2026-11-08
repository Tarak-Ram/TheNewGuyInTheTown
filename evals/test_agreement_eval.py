"""Runs the agreement eval in CI, both on text and through real PDF text layers."""

import json

from agreement_eval import DIR, TARGET, load_labels, run
from agreement_pdf import make_pdf
from nguit_tools.agreement_check import analyze_document, locate
from nguit_tools.agreement_files import pdf_text_pages

PLANTED = {"lock_in", "deposit_deduction", "notice_period", "rent_increase"}


def test_the_sample_set_covers_every_risk_the_prd_names():
    planted = {t for label in load_labels().values() for t in label["risks"]}
    assert PLANTED <= planted
    labels = load_labels()
    assert any(label["injection"] for label in labels.values())  # an injected instruction
    assert any(not label["risks"] for label in labels.values())  # a clean agreement
    assert (
        "synthetic"
        in json.loads((DIR / "labels.json").read_text(encoding="utf-8"))["about"].lower()
    )


def test_rules_check_meets_the_prd_recall_target():
    report = run(None)
    assert report.recall >= TARGET, (report.missed, report.extra)


def test_every_reported_quote_is_really_in_its_document():
    assert run(None).bad_quotes == []


def test_injected_instructions_are_detected_only_where_planted():
    assert run(None).injection_wrong == []


def test_clean_agreement_raises_no_false_alarms():
    report = run(None)
    assert not [e for e in report.extra if e.startswith("f_clean")]


def test_results_are_the_same_through_a_real_pdf_text_layer():
    """Hard line wraps from a real PDF must not change what is found."""
    for name, label in load_labels().items():
        if not label.get("rules_supported", True):
            continue
        text = (DIR / name).read_text(encoding="utf-8")
        pages = pdf_text_pages(make_pdf(text))
        got = {r.type for r in analyze_document(pages, None).risks}
        assert set(label["risks"]) <= got, name
        assert not got - set(label["risks"]), f"{name}: extra {got - set(label['risks'])}"
        for r in analyze_document(pages, None).risks:
            assert locate(r.quote, pages) is not None, name
