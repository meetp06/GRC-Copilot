"""Score retrieval against the golden set. Keyword baseline vs vector search.

    python -m src.rag.evaluate_retrieval

This measures *retrieval only* -- did we fetch the passage that contains the
answer? It does not ask a model to write an answer, so the 5 unanswerable
questions are excluded here: refusal is a generation behaviour, and scoring it
needs the answering step that comes later this week.

Three numbers, and they say different things:

  hit rate  did at least one gold chunk appear in the top k?
            the loosest measure. Good enough for a one-document answer.
  recall    what fraction of ALL gold chunks appeared?
            the hard band needs 2-3 chunks, so hit rate can be 100% while
            recall is 50% and every hard answer is half missing.
  MRR       how high up was the first gold chunk?
            1.0 means it was always rank 1. 0.5 means typically rank 2.
            Rank matters because the model reads the top of the list closest.
"""

from __future__ import annotations

import re
import statistics
from pathlib import Path

import yaml

from src.agent.tools import search_policies
from src.rag.hybrid import HybridRetriever
from src.rag.index import VectorIndex

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SET = REPO_ROOT / "evals" / "golden_set.yaml"
TOP_K = 5

BANDS = ["easy", "medium", "hard", "exact"]
KEYWORD_HIT_RE = re.compile(r"\[source: (\S+).*?\n## (.+)")


def load_questions() -> list[dict]:
    data = yaml.safe_load(GOLDEN_SET.read_text(encoding="utf-8"))
    return [q for q in data["questions"] if q["difficulty"] != "unanswerable"]


def keyword_retrieve(question: str, top_k: int) -> list[tuple[str, str]]:
    """Week 1 search, parsed back into (source, section) pairs.

    It returns formatted text rather than structured hits, which is itself a
    week 1 design smell: a tool that returns prose cannot be evaluated without
    a regex. Week 3 fixes that.
    """
    raw = search_policies(question, top_k=top_k)
    return [(m.group(1), m.group(2).strip()) for m in KEYWORD_HIT_RE.finditer(raw)]


def vector_retrieve(
    index: VectorIndex, question: str, top_k: int
) -> list[tuple[str, str]]:
    return [(h.source, h.section) for h in index.search(question, top_k=top_k)]


def score(
    retrieved: list[tuple[str, str]], gold: list[tuple[str, str]]
) -> dict[str, float]:
    found = [g for g in gold if g in retrieved]
    ranks = [retrieved.index(g) + 1 for g in gold if g in retrieved]
    return {
        "hit": 1.0 if found else 0.0,
        "recall": len(found) / len(gold),
        "rr": 1.0 / min(ranks) if ranks else 0.0,
    }


def evaluate(name: str, retrieve, questions: list[dict]) -> None:
    rows: list[tuple[str, dict[str, float]]] = []
    for q in questions:
        gold = [(c["source"], c["section"]) for c in q["expected_chunks"]]
        rows.append((q["difficulty"], score(retrieve(q["question"]), gold)))

    def mean(band: str | None, key: str) -> float:
        vals = [s[key] for band_name, s in rows if band is None or band_name == band]
        return statistics.mean(vals) if vals else 0.0

    print(f"\n{name}  (top-{TOP_K}, {len(questions)} answerable questions)")
    print(f"{'band':<10}{'n':>4}{'hit rate':>11}{'recall':>9}{'MRR':>8}")
    print("-" * 42)
    for band in [*BANDS, None]:
        label = band or "ALL"
        n = sum(1 for b, _ in rows if band is None or b == band)
        print(
            f"{label:<10}{n:>4}{mean(band, 'hit'):>10.0%}"
            f"{mean(band, 'recall'):>9.0%}{mean(band, 'rr'):>8.2f}"
        )


def main() -> None:
    questions = load_questions()
    index = VectorIndex.load()
    hybrid = HybridRetriever(index)

    evaluate(
        "keyword (week 1 baseline)", lambda q: keyword_retrieve(q, TOP_K), questions
    )
    evaluate(
        "vector (Titan V2, section chunks)",
        lambda q: vector_retrieve(index, q, TOP_K),
        questions,
    )
    evaluate(
        "hybrid (vector + BM25, RRF k=60)",
        lambda q: [(h.source, h.section) for h in hybrid.search(q, top_k=TOP_K)],
        questions,
    )


if __name__ == "__main__":
    main()
