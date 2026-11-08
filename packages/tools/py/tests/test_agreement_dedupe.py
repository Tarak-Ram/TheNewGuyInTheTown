from nguit_tools.agreement_check import PageText, analyze_document


def types(text):
    return [r.type for r in analyze_document([PageText(1, text)], None).risks]


def test_a_penalty_clause_that_mentions_the_lock_in_is_reported_once():
    text = "If the Tenant leaves in the lock-in, the Tenant shall pay a penalty of two months rent."
    assert types(text) == ["early_exit_penalty"]


def test_the_demo_sample_penalty_clause_is_reported_once():
    """The exact sentence from evals/agreements/g_multi (it says 'the lock-in period')."""
    text = (
        "If the Tenant leaves during the lock-in, the Tenant shall pay a penalty equal to "
        "the remaining rent for the lock-in period."
    )
    assert types(text) == ["early_exit_penalty"]


def test_the_sample_agreement_reports_each_clause_once():
    from pathlib import Path

    sample = Path(__file__).resolve().parents[4] / "evals" / "agreements" / "g_multi.txt"
    result = analyze_document([PageText(1, sample.read_text(encoding="utf-8"))], None)
    quotes = [r.quote for r in result.risks]
    assert len(quotes) == len(set(quotes)), "a clause is shown more than once"
    assert sorted(r.type for r in result.risks) == [
        "deposit_deduction", "early_exit_penalty", "eviction_terms", "lock_in", "owner_entry",
    ]  # fmt: skip


def test_a_deposit_clause_that_mentions_the_lock_in_is_reported_once():
    assert types("The deposit is forfeited if the Tenant leaves during the lock-in.") == [
        "deposit_deduction"
    ]


def test_a_real_lock_in_statement_is_still_reported_alongside_a_penalty():
    text = "The lock-in period is 6 months and a penalty applies if the Tenant leaves earlier."
    assert set(types(text)) == {"lock_in", "early_exit_penalty"}


def test_the_lock_in_clause_itself_is_still_found():
    assert types("The Tenant has a lock-in period of 6 months.") == ["lock_in"]
