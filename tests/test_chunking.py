"""Chunking tests. Deterministic, synthetic input, no corpus and no network.

The report in src/rag/report_chunks.py is the measurement; this file is the
proof the measurement is not lying. If chunk_fixed silently dropped its overlap,
the report would still print a plausible table.
"""

from __future__ import annotations

import pytest

from src.rag.chunking import (
    CHARS_PER_TOKEN,
    chunk_by_section,
    chunk_corpus,
    chunk_fixed,
    document_title,
    section_spans,
)

DOC = """# Test Policy

**Owner:** Nobody

## First section

Alpha bravo charlie delta echo foxtrot.

## Second section

Golf hotel india juliet kilo lima mike.
"""


def test_section_spans_are_contiguous_and_named() -> None:
    spans = section_spans(DOC)
    assert [name for name, _, _ in spans] == ["First section", "Second section"]
    assert (
        spans[0][2] == spans[1][1]
    ), "sections must abut, or characters go unattributed"
    assert spans[-1][2] == len(DOC)


def test_document_title() -> None:
    assert document_title(DOC) == "Test Policy"
    assert document_title("no title here") == ""


def test_section_chunks_keep_sections_whole_and_carry_the_title() -> None:
    chunks = chunk_by_section(DOC, "test.md")
    assert len(chunks) == 2
    assert all(len(c.sections) == 1 for c in chunks)
    assert chunks[0].text.startswith("# Test Policy")
    assert "## First section" in chunks[0].text
    assert "Second section" not in chunks[0].text


def test_fixed_chunks_overlap_by_the_requested_amount() -> None:
    text = "x" * 400
    chunks = chunk_fixed(text, "test.md", size_tokens=50, overlap_tokens=10)
    size = 50 * CHARS_PER_TOKEN
    stride = 40 * CHARS_PER_TOKEN
    assert chunks[0].char_start == 0
    assert chunks[0].char_end == size
    assert chunks[1].char_start == stride
    overlap = chunks[0].char_end - chunks[1].char_start
    assert overlap == 10 * CHARS_PER_TOKEN


def test_fixed_chunks_never_exceed_the_window() -> None:
    chunks = chunk_fixed(DOC, "test.md", size_tokens=16, overlap_tokens=4)
    assert all(len(c.text) <= 16 * CHARS_PER_TOKEN for c in chunks)
    assert chunks[-1].char_end == len(DOC)


def test_fixed_chunks_record_every_section_they_straddle() -> None:
    """A window wide enough to cover the whole document must report both
    sections. That count is the precision side of the chunking trade-off."""
    chunks = chunk_fixed(DOC, "test.md", size_tokens=1000, overlap_tokens=0)
    assert len(chunks) == 1
    assert chunks[0].sections == ("First section", "Second section")


def test_overlap_must_be_smaller_than_the_window() -> None:
    """Equal values give a stride of zero, which loops forever."""
    with pytest.raises(ValueError):
        chunk_fixed(DOC, "test.md", size_tokens=64, overlap_tokens=64)


def test_chunk_corpus_parses_strategy_names() -> None:
    corpus = {"test.md": DOC}
    assert len(chunk_corpus("section", corpus)) == 2
    assert all(c.strategy == "fixed-16-4" for c in chunk_corpus("fixed-16-4", corpus))
    with pytest.raises(ValueError):
        chunk_corpus("semantic", corpus)
