"""Check whether the confidence score means anything.

    python -m src.graph.calibrate

A confidence score is a promise: "answers I mark high are usually right". That
promise is either kept or it is not, and the only way to know is to mark a set
of answers whose correctness is already known and count.

The test is per band, not overall. A score that is 90% accurate on average but
90% accurate in every band is useless -- it has not separated anything. What
makes a score worth having is that `high` is meaningfully better than `medium`,
and `medium` than `low`. If they are flat, the score is decoration and the
routing built on it is arbitrary.

Correctness here is retrieval-grounded, not a judgement of wording: an answer is
counted correct when the model chose to answer a question the golden set says is
answerable, and cited at least one of the passages the golden set names. That is
strict about the thing this product sells -- an answer traceable to the right
source -- and silent about style.

The number to act on is precision in the `high` band. Those are the answers that
ship to a customer without a human reading them. Under about 90% there, the
thresholds in confidence.py are wrong.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from pathlib import Path

import yaml
from rich.console import Console

from src.graph.build import build_graph
from src.graph.confidence import retrieval_margin, score
from src.rag.index import VectorIndex

console = Console()

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SET = REPO_ROOT / "evals" / "golden_set.yaml"


def load_questions() -> list[dict]:
    return yaml.safe_load(GOLDEN_SET.read_text(encoding="utf-8"))["questions"]


def is_correct(question: dict, state: dict) -> bool:
    """Did the system do the right thing on this question?

    For an unanswerable question the right thing is to refuse, and refusing is
    the whole answer. For an answerable one it is to answer and to cite at least
    one of the passages the golden set names -- an answer sourced from the wrong
    passage is wrong even when the words happen to be true, because the citation
    is what an auditor checks.
    """
    should_answer = question["difficulty"] != "unanswerable"
    answered = bool(state.get("answerable"))

    if not should_answer:
        return not answered
    if not answered:
        return False

    gold = {(c["source"], c["section"]) for c in question["expected_chunks"]}
    retrieved = state.get("retrieved", [])
    cited = {
        (retrieved[i - 1]["source"], retrieved[i - 1]["section"])
        for i in state.get("citations", [])
        if 1 <= i <= len(retrieved)
    }
    return bool(cited & gold)


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()

    questions = load_questions()
    app = build_graph(VectorIndex.load())

    rows = []
    for question in questions:
        state = app.invoke(
            {
                "question": question["question"],
                "question_id": question["id"],
                "status": "retrieving",
            }
        )
        band, reasons = score(state)
        rows.append(
            {
                "id": question["id"],
                "difficulty": question["difficulty"],
                "band": band,
                "correct": is_correct(question, state),
                "margin": retrieval_margin(state),
                "model_said": state.get("model_confidence"),
                "reasons": reasons,
            }
        )

    console.print(f"\n[bold]Calibration over {len(rows)} questions[/bold]\n")
    console.print(f"{'band':<10}{'n':>5}{'correct':>10}{'precision':>12}")
    console.print("-" * 37)

    by_band: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_band[row["band"]].append(row)

    for band in ("high", "medium", "low"):
        group = by_band.get(band, [])
        if not group:
            console.print(f"{band:<10}{0:>5}{'-':>10}{'-':>12}")
            continue
        correct = sum(1 for r in group if r["correct"])
        console.print(
            f"{band:<10}{len(group):>5}{correct:>10}{correct / len(group):>11.0%}"
        )

    overall = sum(1 for r in rows if r["correct"]) / len(rows)
    console.print(f"\noverall correct   {overall:.0%}")

    # The comparison that matters: the model's own stated confidence, scored the
    # same way. If it separates as well as the computed score, the extra signals
    # are not earning their keep.
    console.print("\n[bold]The model's own confidence, for comparison[/bold]")
    console.print(f"{'model said':<12}{'n':>5}{'precision':>12}")
    console.print("-" * 29)
    by_model: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_model[row["model_said"] or "none"].append(row)
    for said in ("high", "medium", "low", "none"):
        group = by_model.get(said, [])
        if not group:
            continue
        correct = sum(1 for r in group if r["correct"])
        console.print(f"{said:<12}{len(group):>5}{correct / len(group):>11.0%}")

    wrong_and_confident = [r for r in rows if r["band"] == "high" and not r["correct"]]
    if wrong_and_confident:
        console.print(
            f"\n[red]{len(wrong_and_confident)} marked high and wrong[/red] "
            "— these ship to a customer unreviewed:"
        )
        for r in wrong_and_confident:
            console.print(f"  {r['id']} [{r['difficulty']}]  margin={r['margin']:.3f}")

    margins = [r["margin"] for r in rows]
    console.print(
        f"\nretrieval margin: median {statistics.median(margins):.3f}, "
        f"min {min(margins):.3f}, max {max(margins):.3f}"
    )


if __name__ == "__main__":
    main()
