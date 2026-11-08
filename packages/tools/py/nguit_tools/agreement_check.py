"""Finds risky clauses in a rental agreement, and refuses to report anything it cannot quote.

The pipeline, in order:
  1. The document is turned into per-page text (PDF text layer, or a separate transcription).
  2. Text that tries to instruct the AI is found and set aside. It is never obeyed.
  3. A model proposes risks. Every one must quote words that really appear in the page text.
     A risk whose quote cannot be found is dropped (D-3). The page number comes from where
     the quote was found, not from the model.
  4. A rules check runs on the same text and adds any clear risk the model missed. This also
     protects against a model that was talked into ignoring real risks.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel

from nguit_tools.numbers import normalize_numbers

log = logging.getLogger(__name__)

RISK_TYPES = (
    "lock_in",
    "deposit_deduction",
    "notice_period",
    "rent_increase",
    "early_exit_penalty",
    "owner_entry",
    "eviction_terms",
    "other",
)
SEVERITIES = ("high", "medium", "low")
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
MIN_QUOTE_CHARS = 15
MAX_QUOTE_CHARS = 600
MAX_TEXT_CHARS = 60 * 1024  # cap what we send to a model
MIN_READABLE_LETTERS = 200

EXPLANATIONS = {
    "lock_in": "You may have to stay, or keep paying, for a fixed period even if you want to leave.",
    "deposit_deduction": "Part or all of your deposit could be kept, or returned late.",
    "notice_period": "You may need to give a long notice before leaving, or lose money if you do not.",
    "rent_increase": "The rent can go up, possibly by a lot or with little warning.",
    "early_exit_penalty": "Leaving early could cost you a penalty or the rent for the remaining months.",
    "owner_entry": "The owner may enter your room without telling you first.",
    "eviction_terms": "The owner may be able to end the agreement and ask you to leave at short notice.",
    "other": "This clause may be unfavourable to you.",
}
QUESTIONS = {
    "lock_in": "Can the lock-in period be shorter, or can I leave early by finding a replacement?",
    "deposit_deduction": "Exactly what can be deducted from the deposit, and when is the rest returned?",
    "notice_period": "Can the notice period be 30 days? What happens if I give less notice?",
    "rent_increase": "By how much and how often can the rent increase? Can it be written down?",
    "early_exit_penalty": "What exactly do I pay if I leave early, and is there a way to avoid it?",
    "owner_entry": "Can the owner agree to give me notice before entering my room?",
    "eviction_terms": "How much notice will I get if I am asked to leave, and what is my refund?",
    "other": "Can you explain what this clause means for me?",
}

# Text inside a document that talks to the AI instead of to the tenant.
INJECTION = re.compile(
    r"(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|earlier|all)\b.{0,30}"
    r"\b(instruction|rule|prompt|direction)s?|"
    r"\b(system|assistant|ai)\s*(note|prompt|instruction|message)\s*:|"
    r"\b(note|message|instruction)s?\s+(to|for)\s+(the\s+)?(ai|assistant|model|reviewer|checker)\b|"
    r"\b(do not|don't|never)\s+(report|mention|flag|list)\b.{0,40}\b(risk|clause|issue)|"
    r"\b(report|mark|describe|state)\s+(this|the)\s+(agreement|document|contract)\b.{0,30}"
    r"\b(safe|fine|fair|risk[- ]free|no risks?)|"
    r"\bas an ai\b|\byou are now\b|\bnew instructions?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PageText:
    page: int
    text: str


class ModelRisk(BaseModel):
    """One risk as proposed by a model. Types and severities are checked in code."""

    type: str
    severity: str
    page: int | None = None
    quote: str
    quote_translation: str | None = None
    explanation: str
    question_to_ask: str


class AnalysisOutput(BaseModel):
    language: str = "en"
    risks: list[ModelRisk] = []


@dataclass(frozen=True)
class Risk:
    type: str
    severity: str
    page: int | None
    quote: str
    explanation: str
    question_to_ask: str
    quote_translation: str | None = None
    source: str = "model"


@dataclass
class AnalysisResult:
    risks: list[Risk]
    language: str = "en"
    injection_detected: bool = False
    discarded: int = 0
    used_model: bool = False
    warnings: list[str] = field(default_factory=list)


class Analyzer(Protocol):
    name: str

    def analyze(self, pages: list[PageText]) -> AnalysisOutput: ...


# -- text helpers ----------------------------------------------------------------------------
def plain(text: str) -> str:
    """Lower-case words only, so line breaks and punctuation never cause a false mismatch."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def sentences(text: str) -> list[str]:
    """Clause-sized pieces. PDF text is hard-wrapped, so a single line break is not a split."""
    text = re.sub(r"-[ \t]*\n[ \t]*", "-", text)  # "lock-" + newline + "in" -> "lock-in"
    parts = re.split(
        r"(?<!Rs\.)(?<!No\.)(?<!Sl\.)(?<=[.;?!])\s+|\n[ \t]*(?=\d+[.)]\s)|\n\s*\n", text
    )
    cleaned = (re.sub(r"\s+", " ", p).strip() for p in parts)
    return [p for p in cleaned if len(p) >= 8]


def is_readable(pages: list[PageText]) -> bool:
    text = " ".join(p.text for p in pages)
    # Count letters AND combining marks: Hindi and Telugu vowel signs are marks, not letters.
    letters = sum(c.isalpha() or unicodedata.category(c).startswith("M") for c in text)
    visible = sum(not c.isspace() for c in text)
    return letters >= MIN_READABLE_LETTERS and visible > 0 and letters / visible >= 0.5


def find_injections(pages: list[PageText]) -> list[str]:
    return [s for p in pages for s in sentences(p.text) if INJECTION.search(s)]


def text_for_model(pages: list[PageText]) -> str:
    joined = "\n\n".join(f"[[page {p.page}]]\n{p.text}" for p in pages)
    return joined[:MAX_TEXT_CHARS]


# -- verification (D-3) ------------------------------------------------------------------------
def locate(quote: str, pages: list[PageText]) -> int | None:
    """The page where this exact text appears, or None if it is nowhere in the document."""
    q = plain(quote)
    if not q:
        return None
    for p in pages:
        if q in plain(p.text):
            return p.page
    return None


def verify_risks(candidates: list[ModelRisk], pages: list[PageText]) -> tuple[list[Risk], int]:
    """Keeps only risks whose quote is really in the document. Returns (kept, discarded)."""
    kept: list[Risk] = []
    seen: set[tuple[str, str]] = set()
    discarded = 0
    for c in candidates:
        quote = c.quote.strip()
        page = locate(quote, pages) if MIN_QUOTE_CHARS <= len(quote) <= MAX_QUOTE_CHARS else None
        explanation = c.explanation.strip()
        if page is None or not explanation:
            discarded += 1
            continue
        rtype = c.type if c.type in RISK_TYPES else "other"
        key = (rtype, plain(quote))
        if key in seen:
            continue
        seen.add(key)
        severity = c.severity if c.severity in SEVERITIES else "medium"
        kept.append(
            Risk(
                type=rtype,
                severity=severity,
                page=page,  # from the document, not from the model
                quote=quote,
                explanation=explanation[:600],
                question_to_ask=(c.question_to_ask.strip() or QUESTIONS[rtype])[:300],
                quote_translation=(c.quote_translation or "").strip()[:600] or None,
                source="model",
            )
        )
    return kept, discarded


# -- rules check -------------------------------------------------------------------------------
def _months(s: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(day|week|month|year)s?", s)
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2)
    return {"day": n / 30, "week": n / 4.3, "month": n, "year": n * 12}[unit]


def _detect(sentence: str) -> list[tuple[str, str]]:
    """(type, severity) pairs for one sentence. Numbers are read after turning words to digits."""
    s = normalize_numbers(sentence).lower()
    found: list[tuple[str, str]] = []

    no_lock_in = re.search(
        r"\b(no|without|nil)\b[^.]{0,25}lock[- ]?in|lock[- ]?in[^.]{0,25}\b(waived|not applicable|nil)\b",
        s,
    )
    if not no_lock_in and (
        re.search(r"lock[- ]?in", s)
        or re.search(r"(minimum|min\.?)\s+(stay|period|tenure|occupancy)", s)
        or re.search(
            r"(cannot|shall not|may not|not (be )?allowed to)\s+(vacate|leave|move out)", s
        )
    ):
        months = _months(s)
        found.append(("lock_in", "high" if months is None or months >= 6 else "medium"))

    if "deposit" in s:
        severe = re.search(
            r"non[- ]?refundable|forfeit|no refund|not be refunded|not refundable|"
            r"will not be returned|shall not be returned",
            s,
        )
        deduct = re.search(
            r"deduct|withh?eld|adjusted against|painting|whitewash|cleaning charges?|"
            r"damage charges?|at the (sole )?discretion",
            s,
        )
        slow = re.search(r"(refund|return)\w*[^.]{0,60}within\s+(\d+)\s*(day|month)s?", s)
        slow_days = 0.0
        if slow:
            slow_days = float(slow.group(2)) * (30 if slow.group(3) == "month" else 1)
        if severe:
            found.append(("deposit_deduction", "high"))
        elif deduct:
            found.append(("deposit_deduction", "medium"))
        elif slow_days >= 60:
            found.append(("deposit_deduction", "medium"))

    if "notice" in s and re.search(r"(\d+)\s*(day|week|month)s?", s):
        months = _months(s) or 0
        if months >= 3:
            found.append(("notice_period", "high"))
        elif months >= 2:
            found.append(("notice_period", "medium"))

    if re.search(r"\brent\b", s) and re.search(r"increase|revis|escalat|hike|enhance|raise", s):
        pct = re.search(r"(\d+(?:\.\d+)?)\s*%|(\d+(?:\.\d+)?)\s*percent", s)
        value = float(pct.group(1) or pct.group(2)) if pct else None
        arbitrary = re.search(
            r"at any time|sole discretion|without (prior )?(notice|consent)|as the (owner|landlord) "
            r"(decides|deems|wishes)",
            s,
        )
        fair = re.search(
            r"mutual|not be (increased|revised|raised|enhanced)|shall not (increase|revise|raise)|"
            r"only (with|by) (the )?(consent|agreement)",
            s,
        )
        if fair and (value is None or value < 5):
            pass  # a clause that protects the tenant from increases
        elif arbitrary or (value is not None and value >= 10):
            found.append(("rent_increase", "high"))
        elif value is not None and value >= 5:
            found.append(("rent_increase", "medium"))

    no_penalty = re.search(
        r"\b(no|without|nil|free of)\b[^.]{0,20}(penalty|penalties|liquidated)", s
    )
    if not no_penalty and re.search(
        r"penalty|liquidated damages|pay(able)?\s+(the\s+)?(remaining|balance|full)|"
        r"balance\s+(of\s+)?(the\s+)?(rent|term|lock)",
        s,
    ):
        found.append(("early_exit_penalty", "high"))

    if re.search(
        r"\benter\b[^.]{0,50}(at any time|without (any )?(prior )?(notice|permission|consent))", s
    ):
        found.append(("owner_entry", "medium"))

    if re.search(
        r"(terminate|evict|vacate)[^.]{0,60}without (any )?(prior )?(notice|reason)|"
        r"vacate (the room )?immediately|(vacate|leave)[^.]{0,30}within\s+(24|48)\s*hours",
        s,
    ):
        found.append(("eviction_terms", "high"))

    # A penalty or deposit clause that merely mentions "the lock-in" is about money, not about
    # the lock-in itself. Report it once, under the more specific type.
    kinds = {t for t, _ in found}
    # Only a clause that states a duration or an obligation is itself the lock-in.
    states_a_lock_in = re.search(
        r"lock[- ]?in( period)?\s+(of|is|shall be|will be)\s+\d|"
        r"minimum\s+(stay|period|tenure|occupancy)|"
        r"(cannot|shall not|may not)\s+(vacate|leave|move out)",
        s,
    )
    if "lock_in" in kinds and kinds & {"early_exit_penalty", "deposit_deduction"}:
        if not states_a_lock_in:
            found = [f for f in found if f[0] != "lock_in"]
    return found


class RuleAnalyzer:
    """English keyword and number checks. A safety net next to the model, and an offline baseline."""

    name = "rules-v1"

    def analyze(self, pages: list[PageText]) -> AnalysisOutput:
        risks = []
        for p in pages:
            for sentence in sentences(p.text):
                if INJECTION.search(sentence):
                    continue  # never treat attack text as the agreement's own terms
                for rtype, severity in _detect(sentence):
                    risks.append(
                        ModelRisk(
                            type=rtype,
                            severity=severity,
                            page=p.page,
                            quote=sentence[:MAX_QUOTE_CHARS],
                            explanation=EXPLANATIONS[rtype],
                            question_to_ask=QUESTIONS[rtype],
                        )
                    )
        return AnalysisOutput(language="en", risks=risks)


# -- putting it together ---------------------------------------------------------------------
def _overlaps(a: Risk, b: Risk) -> bool:
    if a.type != b.type:
        return False
    pa, pb = plain(a.quote), plain(b.quote)
    if pa in pb or pb in pa:
        return True
    wa, wb = set(pa.split()), set(pb.split())
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.6


def analyze_document(pages: list[PageText], analyzer: Analyzer | None) -> AnalysisResult:
    """Model risks (verified) plus rule risks the model did not already report."""
    injections = find_injections(pages)
    result = AnalysisResult(risks=[], injection_detected=bool(injections))

    model_risks: list[Risk] = []
    if analyzer is not None:
        try:
            out = analyzer.analyze(pages)
            model_risks, result.discarded = verify_risks(out.risks, pages)
            result.language = out.language or "en"
            result.used_model = True
        except Exception:
            log.warning("Model analysis failed; using the rules check only", exc_info=True)
            result.warnings.append("The AI reader was unavailable, so only basic checks ran.")

    # Never report the attack text itself as if it were a clause of the agreement.
    inj_plain = [plain(s) for s in injections]
    model_risks = [r for r in model_risks if not any(plain(r.quote) in s for s in inj_plain)]

    rule_out = RuleAnalyzer().analyze(pages)
    rule_risks, _ = verify_risks(rule_out.risks, pages)
    extra = [
        Risk(**{**r.__dict__, "source": "rules"})
        for r in rule_risks
        if not any(_overlaps(r, m) for m in model_risks)
    ]
    result.risks = sorted(
        model_risks + extra,
        key=lambda r: (SEVERITY_ORDER[r.severity], r.page or 0, r.type),
    )
    if injections:
        result.warnings.append(
            "This document contains text that tries to give instructions to an AI. "
            "It was ignored. Take care, and ask the owner about it."
        )
    return result
