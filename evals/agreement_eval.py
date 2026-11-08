"""Scores the Agreement Checker on the labelled fake agreements.

    python evals/agreement_eval.py                    # rules check only, no keys needed
    python evals/agreement_eval.py --analyzer model   # Gemini + rules, needs GEMINI_TEXT_MODEL

What it reports:
  recall            of the risks we planted, how many were found (PRD D-2: at least 90%)
  extra risk types  risks reported that were not planted (possible false alarms)
  quote check       every reported quote must really be in the document (PRD D-3: 100%)
  injection         the planted "instructions to the AI" are detected and ignored
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("packages/tools/py", "packages/schemas/py"):
    sys.path.insert(0, str(ROOT / sub))

from nguit_tools.agreement_check import PageText, analyze_document, locate  # noqa: E402

DIR = Path(__file__).parent / "agreements"
TARGET = 0.90


@dataclass
class Report:
    expected: int = 0
    found: int = 0
    reported: int = 0
    bad_quotes: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    injection_wrong: list[str] = field(default_factory=list)
    documents: int = 0

    @property
    def recall(self) -> float:
        return self.found / self.expected if self.expected else 1.0


def load_labels() -> dict:
    return json.loads((DIR / "labels.json").read_text(encoding="utf-8"))["documents"]


def read(name: str) -> list[PageText]:
    return [PageText(1, (DIR / name).read_text(encoding="utf-8"))]


def run(analyzer=None, only_rules_supported: bool = True) -> Report:
    report = Report()
    for name, label in load_labels().items():
        if only_rules_supported and not label.get("rules_supported", True):
            continue
        pages = read(name)
        result = analyze_document(pages, analyzer)
        report.documents += 1
        got = {r.type for r in result.risks}
        want = set(label["risks"])
        report.expected += len(want)
        report.found += len(want & got)
        report.reported += len(result.risks)
        report.missed += [f"{name}:{t}" for t in sorted(want - got)]
        report.extra += [f"{name}:{t}" for t in sorted(got - want)]
        report.bad_quotes += [
            f"{name}:{r.quote[:40]}" for r in result.risks if locate(r.quote, pages) is None
        ]
        if result.injection_detected != label["injection"]:
            report.injection_wrong.append(name)
    return report


def print_report(name: str, r: Report) -> None:
    print(f"Analyzer: {name}   ({r.documents} documents, {r.expected} planted risks)")
    print(f"  recall            : {r.recall:.1%}  ({r.found}/{r.expected})  target {TARGET:.0%}")
    print(f"  quotes not in text: {len(r.bad_quotes)}  (must be 0)")
    print(f"  injection errors  : {len(r.injection_wrong)}  (must be 0)")
    print(f"  extra risk types  : {len(r.extra)}")
    for line in r.missed:
        print(f"  missed  {line}")
    for line in r.extra:
        print(f"  extra   {line}")
    for line in r.bad_quotes:
        print(f"  BAD QUOTE {line}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyzer", choices=["rules", "model"], default="rules")
    args = parser.parse_args()
    analyzer = None
    name = "rules-v1"
    if args.analyzer == "model":
        from nguit_tools.agreement_ai import get_analyzer

        analyzer = get_analyzer()
        if analyzer is None:
            print("GEMINI_TEXT_MODEL and a Gemini key are needed for the model eval.")
            return 2
        name = f"{analyzer.name} + rules"
    report = run(analyzer, only_rules_supported=analyzer is None)
    print_report(name, report)
    ok = report.recall >= TARGET and not report.bad_quotes and not report.injection_wrong
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
