"""Score the control mapper against the labelled set, and sweep the threshold.

    python -m src.ontology.evaluate_mapping          # score at the current settings
    python -m src.ontology.evaluate_mapping sweep    # find where the threshold should be

Until now the mapping quality claim was "0.523 looks about right", which is not
a claim. This measures it:

    labelled sections ─▶ run the mapper ─▶ precision, recall, F1
                                        ↘ sweep the threshold

Precision matters more than recall here, and the reason is the product rather
than the maths. A missed mapping shows up as a gap in the gap report, which is
conservative and visible -- someone sees a control with no policy and writes
one. A wrong mapping shows up as coverage that does not exist, and nobody looks
at it again. In a compliance product, claiming a control you cannot evidence is
the failure that matters.

The empty-expectation sections are the ones that make precision meaningful. A
set of only positive examples cannot catch a mapper that maps everything to
something.

Costs about $0.002 per run: the controls and sections are re-embedded each time.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from rich.console import Console

from src.ontology.map import MIN_CONFIDENCE, TOP_CONTROLS_PER_SECTION, base_controls
from src.ontology.store import connect
from src.rag.embeddings import embed_texts

console = Console()

REPO_ROOT = Path(__file__).resolve().parents[2]
LABELLED_SET = REPO_ROOT / "evals" / "control_mapping_set.yaml"


def load_labels() -> list[dict]:
    return yaml.safe_load(LABELLED_SET.read_text(encoding="utf-8"))["sections"]


def score_pairs(conn) -> tuple[list[dict], dict[int, dict[str, float]]]:
    """Every labelled section scored against every base control.

    Embedding once and thresholding afterwards is what makes the sweep cheap:
    one run of the model, then arithmetic.
    """
    labels = load_labels()
    controls = base_controls(conn)
    ids = [c["id"] for c in controls]

    sections = []
    for label in labels:
        row = conn.execute(
            "SELECT id, section, text FROM policy_section WHERE id = ?",
            (label["section_id"],),
        ).fetchone()
        if row is None:
            raise SystemExit(
                f"section {label['section_id']} ({label['section']}) is not in the "
                "database. Run: python -m src.ontology.store load"
            )
        sections.append(row)

    control_vectors = embed_texts(
        [f"{c['label']} {c['title']}. {c['statement']}"[:2000] for c in controls]
    )
    section_vectors = embed_texts(
        [f"{s['section']}. {s['text']}"[:2000] for s in sections]
    )
    similarity = section_vectors.vectors @ control_vectors.vectors.T

    by_section = {
        label["section_id"]: dict(zip(ids, similarity[i], strict=True))
        for i, label in enumerate(labels)
    }
    return labels, by_section


def evaluate(
    labels: list[dict],
    scores: dict[int, dict[str, float]],
    threshold: float,
    top_k: int,
) -> dict:
    """Precision, recall and F1 over all labelled sections at one threshold."""
    true_positive = false_positive = false_negative = 0
    per_section = []

    for label in labels:
        expected = set(label["expected"])
        ranked = sorted(scores[label["section_id"]].items(), key=lambda kv: -kv[1])
        predicted = {cid for cid, score in ranked[:top_k] if score >= threshold}

        hits = predicted & expected
        true_positive += len(hits)
        false_positive += len(predicted - expected)
        false_negative += len(expected - predicted)
        per_section.append(
            {
                "section": label["section"],
                "expected": sorted(expected),
                "predicted": sorted(predicted),
                "missed": sorted(expected - predicted),
                "spurious": sorted(predicted - expected),
            }
        )

    precision = (
        true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else 0.0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": threshold,
        "top_k": top_k,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
        "per_section": per_section,
    }


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    conn = connect()
    labels, scores = score_pairs(conn)

    if len(sys.argv) > 1 and sys.argv[1] == "sweep":
        console.print(
            f"\n[bold]Threshold sweep[/bold] over {len(labels)} labelled sections\n"
        )
        console.print(
            f"  {'thresh':>7}{'top_k':>7}{'prec':>8}{'recall':>8}{'F1':>7}{'FP':>5}{'FN':>5}"
        )
        for top_k in (3, 5):
            for threshold in (0.30, 0.35, 0.40, 0.45, 0.50, 0.55):
                r = evaluate(labels, scores, threshold, top_k)
                console.print(
                    f"  {r['threshold']:>7.2f}{r['top_k']:>7}{r['precision']:>8.0%}"
                    f"{r['recall']:>8.0%}{r['f1']:>7.2f}{r['fp']:>5}{r['fn']:>5}"
                )
        return

    result = evaluate(labels, scores, MIN_CONFIDENCE, TOP_CONTROLS_PER_SECTION)
    console.print(
        f"\n[bold]Control mapping[/bold] at threshold {result['threshold']}, "
        f"top {result['top_k']} per section\n"
    )
    console.print(
        f"  precision  {result['precision']:.0%}   ({result['fp']} wrong mappings)"
    )
    console.print(f"  recall     {result['recall']:.0%}   ({result['fn']} missed)")
    console.print(f"  F1         {result['f1']:.2f}")

    console.print("\n[bold]Per section[/bold]")
    for row in result["per_section"]:
        problems = []
        if row["missed"]:
            problems.append(f"[yellow]missed {row['missed']}[/yellow]")
        if row["spurious"]:
            problems.append(f"[red]wrong {row['spurious']}[/red]")
        status = "  ".join(problems) if problems else "[green]exact[/green]"
        console.print(f"  {row['section'][:44]:<46} {status}")


if __name__ == "__main__":
    main()
