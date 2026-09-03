"""Compare chunking strategies on the real corpus. No model calls, no cost.

Run: python -m src.rag.report_chunks

The number that matters is `gold intact`. Every question in the golden set names
the sections that contain its answer. If a chunk boundary cuts one of those
sections in half, no embedding model and no reranker can recover it -- the
answer is not present in any single retrievable unit. That is a chunking
failure, and it is measurable before spending a cent on embeddings.

`sections/chunk` is the other side of the trade. A window large enough to keep
every answer intact also drags in neighbouring sections, so a retrieved chunk is
mostly text the question did not ask about. Recall up, precision down.
"""

from __future__ import annotations

import statistics
from pathlib import Path

import yaml

from src.rag.chunking import Chunk, chunk_corpus, load_corpus, section_spans

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_SET = REPO_ROOT / "evals" / "golden_set.yaml"

STRATEGIES = ["section", "fixed-512-64", "fixed-128-16"]


def gold_sections() -> list[tuple[str, str]]:
    """Every (document, section) pair named as a gold chunk, deduplicated."""
    data = yaml.safe_load(GOLDEN_SET.read_text(encoding="utf-8"))
    pairs = {
        (chunk["source"], chunk["section"])
        for question in data["questions"]
        for chunk in question["expected_chunks"]
    }
    return sorted(pairs)


def gold_intactness(
    chunks: list[Chunk], corpus: dict[str, str], gold: list[tuple[str, str]]
) -> tuple[int, list[str]]:
    """Count gold sections that survive whole inside a single chunk.

    A section is intact if some chunk's character span fully contains the
    section's span. Anything else is split: retrieving the right chunk still
    gives a partial answer.
    """
    by_source: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        by_source.setdefault(chunk.source, []).append(chunk)

    intact = 0
    split: list[str] = []
    for source, section in gold:
        spans = {name: (s, e) for name, s, e in section_spans(corpus[source])}
        start, end = spans[section]
        contained = any(
            c.char_start <= start and c.char_end >= end
            for c in by_source.get(source, [])
        )
        if contained:
            intact += 1
        else:
            split.append(f"{source}:{section}")
    return intact, split


def main() -> None:
    corpus = load_corpus()
    gold = gold_sections()

    header = f"{'strategy':<16}{'chunks':>8}{'med tok':>9}{'max tok':>9}{'sec/chunk':>11}{'gold intact':>13}"
    print(f"corpus: {len(corpus)} documents, {len(gold)} distinct gold sections\n")
    print(header)
    print("-" * len(header))

    splits: dict[str, list[str]] = {}
    for strategy in STRATEGIES:
        chunks = chunk_corpus(strategy, corpus)
        tokens = [c.est_tokens for c in chunks]
        sections_per_chunk = statistics.mean(len(c.sections) for c in chunks)
        intact, split = gold_intactness(chunks, corpus, gold)
        splits[strategy] = split
        print(
            f"{strategy:<16}{len(chunks):>8}{statistics.median(tokens):>9.0f}"
            f"{max(tokens):>9}{sections_per_chunk:>11.2f}"
            f"{f'{intact}/{len(gold)}':>13}"
        )

    for strategy, split in splits.items():
        if split:
            print(
                f"\n{strategy} splits {len(split)} gold sections across chunk boundaries:"
            )
            for name in split:
                print(f"  - {name}")


if __name__ == "__main__":
    main()
