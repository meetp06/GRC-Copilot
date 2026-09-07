"""Parser tests. Synthetic input, no PDFs, no network, no cost."""

from __future__ import annotations

from src.pipeline.parse import (
    Line,
    Section,
    drop_empty_sections,
    headings_by_font,
    is_contents_line,
    looks_like_slides,
    quality_problems,
    recover_sections,
)


def line(text: str, size: float = 12.0, bold: bool = False) -> Line:
    return Line(text=text, size=size, bold=bold, page=0)


BODY = "x" * 200


def test_roman_numeral_headings_are_found_by_text() -> None:
    """The regression that started this: the first pattern list required digits,
    so a document headed I. Purpose / II. Scope reported no structure at all."""
    lines = [
        line("I. Purpose"),
        line(BODY),
        line("II. Scope"),
        line(BODY),
        line("III. Definitions"),
        line(BODY),
    ]
    sections, method, _ = recover_sections(lines, body_size=12.0)
    assert method == "text"
    assert [s.heading for s in sections] == [
        "I. Purpose",
        "II. Scope",
        "III. Definitions",
    ]


def test_font_is_used_when_text_patterns_find_nothing() -> None:
    """Some documents only ever had visual structure. Extraction discards it,
    so the font data is the last place the headings still exist."""
    lines = [
        line("Overview", size=16),
        line(BODY),
        line("Purpose", size=16),
        line(BODY),
        line("Scope", size=16),
        line(BODY),
    ]
    sections, method, _ = recover_sections(lines, body_size=12.0)
    assert method == "font"
    assert len(sections) == 3


def test_page_numbers_are_not_headings() -> None:
    """Page numbers are often set in the same style as headings, and there are
    enough of them to swamp the result."""
    lines = [line("1", size=16), line("Overview", size=16), line("2", size=16)]
    assert headings_by_font(lines, body_size=12.0) == [1]


def test_empty_sections_are_dropped() -> None:
    """A real policy PDF is not all policy -- cover page, contents, revision
    table and signature block are all styled like headings. One document gave 33
    sections of which 18 had no body at all."""
    sections = [
        Section("Version 1.0", ""),
        Section("Contents", "....................... 3"),
        Section("Overview", BODY),
        Section("Purpose", BODY),
        Section("Scope", BODY),
    ]
    kept = drop_empty_sections(sections)
    assert [s.heading for s in kept] == ["Overview", "Purpose", "Scope"]


def test_contents_lines_are_recognised_by_their_dots() -> None:
    assert is_contents_line("Acceptable Use ................. 3")
    assert not is_contents_line("Access is granted on a least-privilege basis.")


def test_a_method_producing_duplicate_headings_is_rejected() -> None:
    """Repeated headings mean the method is matching a visual style rather than
    a document structure."""
    sections = [Section("Document", BODY) for _ in range(5)]
    assert any("duplicate" in p for p in quality_problems(sections))


def test_a_slide_deck_is_not_a_policy() -> None:
    """A folder of policies collected from the internet contained a 70-page
    deck about incident response. Nothing else in the pipeline would notice, and
    it would be cited to a customer as company policy."""
    lines = [line("Agenda"), line("Slides Key:"), line("Questions?")]
    assert looks_like_slides(lines, pages=70)


def test_a_dense_policy_with_an_agenda_is_not_mistaken_for_slides() -> None:
    """Two signals are required together, because a policy can have an agenda
    and a dense document can have short pages."""
    lines = [line("Agenda"), line("y" * 5000)]
    assert not looks_like_slides(lines, pages=2)
