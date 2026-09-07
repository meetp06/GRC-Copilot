"""Fail the build when retrieval quality regresses.

    python scripts/eval_gate.py

Lint catches code that will not run. Tests catch code that runs wrongly. Neither
notices when a prompt change or a chunking tweak drops answer quality, because
nothing throws -- the system keeps answering, just worse. This is the check for
that, and it is the reason the eval set from week 2 exists.

    golden set ─▶ retrieval ─▶ compare to floors ─▶ exit 0 or 1

Two things make the thresholds honest rather than decorative:

  They sit below the current numbers, not at them. Week 3 measured this
  pipeline's run-to-run variance at roughly two questions, so a gate set at
  today's exact score would fail on noise and get disabled within a week -- and
  a disabled gate is worse than none, because it looks like coverage.

  They are floors on the metrics that matter, not on an average. Overall recall
  can hold steady while the medium band collapses, and the medium band is the
  entire argument for embeddings over keyword search.
"""

from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.rag.evaluate_retrieval import (  # noqa: E402
    TOP_K,
    load_questions,
    score,
    vector_retrieve,
)
from src.rag.index import VectorIndex  # noqa: E402

# Measured on 2026-09-04: overall 97%, medium 100%, hard 92%, MRR 0.93.
# Set roughly five points below each, which is more than twice the observed
# variance, so a failure means a real regression rather than a bad afternoon.
FLOORS = {
    "recall_all": 0.90,
    "recall_medium": 0.90,
    "recall_hard": 0.80,
    "mrr_all": 0.85,
}


def main() -> int:
    # In CI the credentials come from OIDC; locally they come from .env. Loading
    # here rather than at import keeps this importable without either.
    from dotenv import load_dotenv

    load_dotenv()

    questions = load_questions()
    index = VectorIndex.load()

    rows = []
    for question in questions:
        gold = [(c["source"], c["section"]) for c in question["expected_chunks"]]
        retrieved = vector_retrieve(index, question["question"], TOP_K)
        rows.append((question["difficulty"], score(retrieved, gold)))

    def mean(band: str | None, key: str) -> float:
        values = [s[key] for b, s in rows if band is None or b == band]
        return statistics.mean(values) if values else 0.0

    measured = {
        "recall_all": mean(None, "recall"),
        "recall_medium": mean("medium", "recall"),
        "recall_hard": mean("hard", "recall"),
        "mrr_all": mean(None, "rr"),
    }

    failures = []
    print(f"{'metric':<16}{'measured':>10}{'floor':>8}")
    print("-" * 34)
    for name, floor in FLOORS.items():
        value = measured[name]
        ok = value >= floor
        print(f"{name:<16}{value:>10.2f}{floor:>8.2f}  {'' if ok else 'FAIL'}")
        if not ok:
            failures.append(f"{name} {value:.2f} < {floor:.2f}")

    if failures:
        print("\nRetrieval regressed:")
        for failure in failures:
            print(f"  {failure}")
        print(
            "\nIf this change is intended, move the floor in scripts/eval_gate.py "
            "in the same commit and say why in the message."
        )
        return 1

    print("\nAll floors met.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
