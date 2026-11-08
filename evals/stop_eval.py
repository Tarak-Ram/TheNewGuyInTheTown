"""Scores how well "the owner wants the calls to stop" is noticed.

    python evals/stop_eval.py                    # pattern levels only, no keys needed
    python evals/stop_eval.py --classifier model # adds the Gemini second opinion (needs a key)

Three numbers, in this order of importance:
  missed            real stop requests that nothing noticed. Must be as close to 0 as possible.
  wrong opt-outs    ordinary talk treated as a CLEAR stop (opts a PG out for all movers). Must be 0.
  needless asks     ordinary talk that made the agent ask "stop calling you?". Cheap, but they
                    annoy people, so keep them low.

The 'holdout 5' set was never tuned on. Its score is the honest estimate for phrasing the
patterns have not seen. Everything else was tuned on, so it only guards against regressions.
"""

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("apps/voice-gateway", "packages/schemas/py", "packages/tools/py"):
    sys.path.insert(0, str(ROOT / sub))

from voice_gateway.stopwords import (  # noqa: E402
    is_end_request,
    is_stop_request,
    needs_stop_confirmation,
)

CASES = Path(__file__).parent / "stop_requests" / "cases.json"
UNSEEN = "holdout 5 (never tuned on)"


@dataclass
class Report:
    by_source: dict = field(default_factory=lambda: defaultdict(lambda: {"n": 0, "missed": []}))
    level1: int = 0
    level2: int = 0
    level3: int = 0
    classifier_rescued: int = 0
    wrong_opt_outs: list[str] = field(default_factory=list)
    needless_asks: list[str] = field(default_factory=list)
    normal: int = 0

    @property
    def total(self) -> int:
        return sum(v["n"] for v in self.by_source.values())

    @property
    def missed(self) -> list[str]:
        return [t for v in self.by_source.values() for t in v["missed"]]

    def recall(self, source: str | None = None) -> float:
        items = [self.by_source[source]] if source else list(self.by_source.values())
        n = sum(v["n"] for v in items)
        return 1 - sum(len(v["missed"]) for v in items) / n if n else 1.0


def load() -> dict:
    return json.loads(CASES.read_text(encoding="utf-8"))


def run(classifier=None) -> Report:
    data = load()
    report = Report()
    for case in data["stops"]:
        text, bucket = case["text"], report.by_source[case["source"]]
        bucket["n"] += 1
        if is_stop_request(text):
            report.level1 += 1
        elif is_end_request(text):
            report.level3 += 1
        elif needs_stop_confirmation(text):
            report.level2 += 1
        elif classifier is not None and asyncio.run(classifier.means_stop(text)):
            report.level2 += 1
            report.classifier_rescued += 1
        else:
            bucket["missed"].append(text)
    for case in data["normal"]:
        text = case["text"]
        report.normal += 1
        if is_stop_request(text) or is_end_request(text):
            report.wrong_opt_outs.append(text)
        elif needs_stop_confirmation(text):
            report.needless_asks.append(text)
        elif classifier is not None and asyncio.run(classifier.means_stop(text)):
            report.needless_asks.append(text)
    return report


def print_report(label: str, r: Report) -> None:
    print(f"Detector: {label}   ({r.total} stop phrases, {r.normal} normal phrases)")
    print(
        f"  noticed overall      : {r.recall():.0%}   (level 1: {r.level1}, ask: {r.level2}, "
        f"end only: {r.level3}, classifier rescued: {r.classifier_rescued})"
    )
    print(f"  NEVER-TUNED set      : {r.recall(UNSEEN):.0%}   <- the honest number")
    print(f"  wrong opt-outs       : {len(r.wrong_opt_outs)}   (must be 0)")
    print(f"  needless questions   : {len(r.needless_asks)} of {r.normal}")
    for text in r.wrong_opt_outs:
        print(f"    WRONG OPT-OUT: {text}")
    for text in r.missed[:12]:
        print(f"    missed: {text}")
    if len(r.missed) > 12:
        print(f"    ... and {len(r.missed) - 12} more")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--classifier", choices=["none", "model"], default="none")
    args = parser.parse_args()
    classifier, label = None, "patterns only"
    if args.classifier == "model":
        from voice_gateway.stop_classifier import get_stop_classifier

        classifier = get_stop_classifier()
        if classifier is None:
            print("GEMINI_TEXT_MODEL and a Gemini key are needed for the model run.")
            return 2
        label = f"patterns + {classifier.model}"
    report = run(classifier)
    print_report(label, report)
    return 0 if not report.wrong_opt_outs else 1


if __name__ == "__main__":
    sys.exit(main())
