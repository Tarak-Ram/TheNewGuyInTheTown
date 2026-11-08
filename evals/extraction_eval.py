"""Scores an extractor against hand-labelled transcripts.

    python evals/extraction_eval.py                  # rules baseline, no keys needed
    python evals/extraction_eval.py --extractor model  # Gemini, needs GEMINI_TEXT_MODEL + key

Three numbers matter, in this order:
  false confirmations  a value saved as confirmed that is wrong, or that nobody stated. Must be 0.
  stated-field recall  of the facts the owner clearly stated, how many were saved correctly.
  overall accuracy     every field in every case, counting 'not confirmed' as correct when right.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("packages/tools/py", "packages/schemas/py"):
    sys.path.insert(0, str(ROOT / sub))

from nguit_tools.call_gate import CALL_FIELDS  # noqa: E402
from nguit_tools.extraction import Segment, extract_facts  # noqa: E402

CASES = Path(__file__).parent / "extraction" / "cases.json"
TARGET = 0.90  # PRD C-4: at least 90% field accuracy


@dataclass
class Report:
    total_fields: int = 0
    correct_fields: int = 0
    stated: int = 0
    stated_correct: int = 0
    false_confirmations: list[str] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct_fields / self.total_fields if self.total_fields else 0.0

    @property
    def recall(self) -> float:
        return self.stated_correct / self.stated if self.stated else 0.0


def load_cases() -> list[dict]:
    return json.loads(CASES.read_text(encoding="utf-8"))["cases"]


def to_segments(case: dict) -> list[Segment]:
    return [
        Segment(i, s["speaker"], (i + 1) * 4000, s["text"]) for i, s in enumerate(case["segments"])
    ]


def run(extractor, cases: list[dict] | None = None) -> Report:
    report = Report()
    for case in cases or load_cases():
        facts = extract_facts(to_segments(case), extractor)
        for name in CALL_FIELDS:
            want = case["expected"].get(name)
            got = facts[name]
            report.total_fields += 1
            if want is None:
                ok = not got.confirmed and got.value is None
                if got.confirmed:
                    report.false_confirmations.append(f"{case['id']}.{name}={got.value!r}")
            else:
                report.stated += 1
                ok = got.confirmed and got.value == want["value"]
                if ok:
                    report.stated_correct += 1
                elif got.confirmed:
                    report.false_confirmations.append(
                        f"{case['id']}.{name}={got.value!r} (expected {want['value']!r})"
                    )
                else:
                    report.misses.append(f"{case['id']}.{name} (expected {want['value']!r})")
            report.correct_fields += ok
    return report


def print_report(name: str, report: Report) -> None:
    n = len(load_cases())
    print(f"Extractor: {name}   ({n} transcripts, {report.total_fields} fields)")
    print(f"  false confirmations : {len(report.false_confirmations)}  (must be 0)")
    print(f"  stated-field recall : {report.recall:.1%}  ({report.stated_correct}/{report.stated})")
    print(f"  overall accuracy    : {report.accuracy:.1%}  (target {TARGET:.0%})")
    for line in report.false_confirmations:
        print(f"  WRONG   {line}")
    for line in report.misses:
        print(f"  missed  {line}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extractor", choices=["rules", "model"], default="rules")
    args = parser.parse_args()

    from nguit_tools.extractors import GeminiExtractor, RuleExtractor

    if args.extractor == "model":
        import os

        model = os.environ.get("GEMINI_TEXT_MODEL")
        if not model:
            print("GEMINI_TEXT_MODEL is not set, so the model eval cannot run.")
            return 2
        extractor = GeminiExtractor(model)
    else:
        extractor = RuleExtractor()
    report = run(extractor)
    print_report(extractor.name, report)
    return 0 if not report.false_confirmations and report.accuracy >= TARGET else 1


if __name__ == "__main__":
    sys.exit(main())
