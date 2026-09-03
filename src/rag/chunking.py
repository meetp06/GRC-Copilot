"""Chunking strategies for the policy corpus.

Two strategies, one interface, so they can be measured against each other rather
than argued about:

  - fixed(size, overlap): the tutorial default. Slides a window over the raw
    document and ignores structure.
  - section: splits on markdown '## ' headings and keeps each section whole,
    prepending the document title so an isolated chunk still says which policy
    it came from.

Token counts are estimated as len(text) // 4. That is a heuristic, not a real
tokenizer -- Bedrock's Titan tokenizer is not available locally, and borrowing
tiktoken would give a precise count for the wrong model family. Both strategies
are measured with the same estimator, so the comparison between them holds even
though the absolute numbers are approximate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

POLICY_DIR = Path(__file__).resolve().parents[2] / "data" / "policies"

CHARS_PER_TOKEN = 4
HEADING_RE = re.compile(r"^## (.+)$", re.MULTILINE)
TITLE_RE = re.compile(r"^# (.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Chunk:
    """One retrievable unit.

    `sections` is every '## ' section this chunk overlaps. Section-aware chunks
    always have exactly one; fixed-size chunks routinely straddle two or three,
    which is the precision cost of ignoring structure.
    """

    text: str
    source: str
    sections: tuple[str, ...]
    strategy: str
    index: int
    char_start: int
    char_end: int

    @property
    def est_tokens(self) -> int:
        return estimate_tokens(self.text)


def estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def load_corpus(policy_dir: Path = POLICY_DIR) -> dict[str, str]:
    """Read every policy document, keyed by filename."""
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(policy_dir.glob("*.md"))
    }


def section_spans(text: str) -> list[tuple[str, int, int]]:
    """Return (heading, start, end) character spans for each '## ' section.

    The span runs from the heading line to the start of the next heading, so
    every character of the document body belongs to at most one section.
    """
    matches = list(HEADING_RE.finditer(text))
    spans: list[tuple[str, int, int]] = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        spans.append((match.group(1).strip(), match.start(), end))
    return spans


def document_title(text: str) -> str:
    match = TITLE_RE.search(text)
    return match.group(1).strip() if match else ""


def _overlapping_sections(
    spans: list[tuple[str, int, int]], start: int, end: int
) -> tuple[str, ...]:
    return tuple(name for name, s, e in spans if s < end and start < e)


def chunk_fixed(
    text: str, source: str, size_tokens: int, overlap_tokens: int
) -> list[Chunk]:
    """Slide a fixed window over the document, ignoring headings.

    Window and stride are computed in characters via the token estimate, so a
    chunk boundary can land anywhere -- including the middle of the sentence
    that answers a question.
    """
    if overlap_tokens >= size_tokens:
        raise ValueError("overlap must be smaller than the window")

    size = size_tokens * CHARS_PER_TOKEN
    stride = (size_tokens - overlap_tokens) * CHARS_PER_TOKEN
    spans = section_spans(text)
    strategy = f"fixed-{size_tokens}-{overlap_tokens}"

    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        body = text[start:end]
        if body.strip():
            chunks.append(
                Chunk(
                    text=body,
                    source=source,
                    sections=_overlapping_sections(spans, start, end),
                    strategy=strategy,
                    index=len(chunks),
                    char_start=start,
                    char_end=end,
                )
            )
        if end == len(text):
            break
        start += stride
    return chunks


def chunk_by_section(text: str, source: str) -> list[Chunk]:
    """One chunk per '## ' section, with the document title prepended.

    The title matters: 'Critical severity findings are remediated within 7 days'
    is ambiguous on its own. Prefixed with 'Vulnerability Management Policy' it
    carries its own context into the index.
    """
    title = document_title(text)
    chunks: list[Chunk] = []
    for name, start, end in section_spans(text):
        body = text[start:end].strip()
        prefixed = f"# {title}\n\n{body}" if title else body
        chunks.append(
            Chunk(
                text=prefixed,
                source=source,
                sections=(name,),
                strategy="section",
                index=len(chunks),
                char_start=start,
                char_end=end,
            )
        )
    return chunks


def chunk_corpus(strategy: str, corpus: dict[str, str] | None = None) -> list[Chunk]:
    """Chunk every document with one named strategy.

    Strategy names: 'section', or 'fixed-<size>-<overlap>' in estimated tokens.
    """
    corpus = load_corpus() if corpus is None else corpus

    if strategy == "section":
        chunker = chunk_by_section
    elif match := re.fullmatch(r"fixed-(\d+)-(\d+)", strategy):
        size, overlap = int(match.group(1)), int(match.group(2))

        def chunker(text: str, source: str) -> list[Chunk]:
            return chunk_fixed(text, source, size, overlap)
    else:
        raise ValueError(f"unknown strategy: {strategy}")

    return [chunk for source, text in corpus.items() for chunk in chunker(text, source)]
