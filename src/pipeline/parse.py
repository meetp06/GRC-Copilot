"""Turn a real PDF into the shape the week 2 chunker already understands.

    python -m src.pipeline.parse pdf_data
    python -m src.pipeline.parse pdf_data --write data/policies_real

Weeks 1 to 3 ran on markdown with clean `##` headings. ADR-0005 chose
section-aware chunking on the argument that policy documents carry a
human-curated segmentation in their headings. Real PDFs do carry it -- but
sometimes only as font size, and text extraction throws that away.

So headings are recovered by a cascade, not one method, and which one won is
recorded per document:

  1. text patterns   Numbered, Roman-numbered, lettered, or all-caps lines.
                     Free, and correct where it fires.
  2. font            A line set larger or bolder than the document's body text.
                     Needed where the structure was only ever visual.
  3. none            Give up and say so. A document nobody can segment is
                     flagged rather than silently indexed as one huge chunk.

Step 3 matters as much as the other two. The failure this replaces is not an
exception -- it is a document quietly becoming a single 70-page chunk that
retrieval returns for everything.

Every document also gets a genre check. A folder of "policies" collected from
the internet contained a 70-page slide deck about incident response, which
would otherwise have been indexed and cited to a customer as company policy.

No model is called. This costs nothing.
"""

from __future__ import annotations

import hashlib
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
from rich.console import Console

from src.pipeline.inventory import find_review_date, looks_like_heading

console = Console()

# A line is a heading candidate by font if it is set at least this much larger
# than the document's most common character size, or is bold at body size.
FONT_SIZE_MARGIN = 0.5

# Headings are short. A "heading" longer than this is a wrapped paragraph.
MAX_HEADING_CHARS = 80

# Fewer sections than this in a document of real length means the cascade did
# not actually find structure, whatever it reported.
MIN_USEFUL_SECTIONS = 3

# Phrases that say "this is a presentation, not a policy". Slide decks exported
# to PDF read as policy documents to every heuristic except this one.
SLIDE_MARKERS = (
    "slides key",
    "agenda",
    "this presentation",
    "in this deck",
    "questions?",
    "thank you!",
    "learning objectives",
)


@dataclass
class Section:
    heading: str
    text: str


@dataclass
class ParsedDocument:
    path: Path
    title: str
    sections: list[Section] = field(default_factory=list)
    heading_method: str = "none"
    review_date: str | None = None
    tables: int = 0
    pages: int = 0
    sha256: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        """Whether this document should reach the index at all."""
        return not any(
            w.startswith(("not a policy", "no structure")) for w in self.warnings
        )


# --------------------------------------------------------------------------
# line extraction


@dataclass(frozen=True)
class Line:
    text: str
    size: float
    bold: bool
    page: int


def extract_lines(pdf) -> tuple[list[Line], float]:
    """Every line of the document with its dominant font size and weight.

    Lines are rebuilt by grouping characters that share a vertical position,
    because pdfplumber's extract_text() gives strings with the font information
    already discarded -- and the font is the only structure some of these
    documents have left.
    """
    grouped: dict[tuple[int, int], list[dict]] = {}
    sizes: Counter[float] = Counter()

    for page_number, page in enumerate(pdf.pages):
        for char in page.chars:
            grouped.setdefault((page_number, round(char["top"])), []).append(char)
            sizes[round(char["size"], 1)] += 1

    body_size = sizes.most_common(1)[0][0] if sizes else 0.0

    lines: list[Line] = []
    for (page_number, _), chars in sorted(grouped.items()):
        text = "".join(c["text"] for c in chars).strip()
        if not text:
            continue
        lines.append(
            Line(
                text=text,
                size=max(round(c["size"], 1) for c in chars),
                bold=any("bold" in c["fontname"].lower() for c in chars),
                page=page_number,
            )
        )
    return lines, body_size


# --------------------------------------------------------------------------
# the heading cascade


def headings_by_text(lines: list[Line]) -> list[int]:
    """Indices of lines that look like headings from their text alone."""
    return [i for i, line in enumerate(lines) if looks_like_heading(line.text)]


def headings_by_font(lines: list[Line], body_size: float) -> list[int]:
    """Indices of lines set larger or bolder than the body text.

    Excludes anything too long to be a heading, and anything that is only
    digits -- page numbers are set in the same style as headings often enough
    to swamp the result otherwise.
    """
    found: list[int] = []
    for i, line in enumerate(lines):
        if len(line.text) > MAX_HEADING_CHARS or line.text.strip().isdigit():
            continue
        bigger = line.size > body_size + FONT_SIZE_MARGIN
        bold_at_body = line.bold and line.size >= body_size
        if bigger or bold_at_body:
            found.append(i)
    return found


def split_into_sections(lines: list[Line], heading_indices: list[int]) -> list[Section]:
    """Everything from one heading to the next is that heading's section."""
    sections: list[Section] = []
    for position, start in enumerate(heading_indices):
        end = (
            heading_indices[position + 1]
            if position + 1 < len(heading_indices)
            else len(lines)
        )
        body = " ".join(line.text for line in lines[start + 1 : end]).strip()
        sections.append(Section(heading=lines[start].text.strip(), text=body))
    return sections


# A table-of-contents line is mostly leader dots. Anything above this ratio of
# dots to characters is navigation, not content.
MAX_DOT_RATIO = 0.3

# Real sections have prose in them. A section whose body is shorter than this is
# a heading with nothing under it.
MIN_SECTION_CHARS = 60

# If this fraction of a method's headings are duplicates, the method is matching
# a visual style rather than a document structure.
MAX_DUPLICATE_HEADING_RATIO = 0.2


def is_contents_line(text: str) -> bool:
    """Leader dots, as in 'Acceptable Use .......... 3'."""
    if not text:
        return False
    return text.count(".") / len(text) > MAX_DOT_RATIO


def drop_empty_sections(sections: list[Section]) -> list[Section]:
    """Keep only sections that actually contain prose.

    A real policy PDF is not all policy. There is a cover page, a table of
    contents, a revision-tracking table and a signature block, and every line in
    those is styled like a heading. One document here produced 33 sections of
    which 18 had zero body text -- so the structure was found correctly and then
    buried in front matter.

    Dropping them is not a quality judgement about the document. It is the
    observation that a heading with nothing under it is not a retrievable unit.
    """
    return [
        s
        for s in sections
        if len(s.text) >= MIN_SECTION_CHARS and not is_contents_line(s.text)
    ]


def quality_problems(sections: list[Section]) -> list[str]:
    """Why a set of sections should not be trusted, or an empty list.

    This exists because the first version of the cascade gated on a section
    *count*, and a count says nothing about content. The font method produced 33
    sections for one document and every one of them was front matter or a table
    of contents entry -- headings like "Version 1.0", "Contents" and "Document",
    with bodies made of leader dots. It passed the count gate cleanly.
    """
    if not sections:
        return ["no sections"]

    problems: list[str] = []

    contents_like = sum(1 for s in sections if is_contents_line(s.text))
    if contents_like > len(sections) / 3:
        problems.append(
            f"{contents_like} of {len(sections)} sections are table-of-contents lines"
        )

    headings = [s.heading.strip().lower() for s in sections]
    duplicates = len(headings) - len(set(headings))
    if duplicates > len(headings) * MAX_DUPLICATE_HEADING_RATIO:
        problems.append(
            f"{duplicates} duplicate headings, matching a style rather than a structure"
        )

    if len(sections) < MIN_USEFUL_SECTIONS:
        problems.append(f"only {len(sections)} sections survived with body text")

    return problems


def recover_sections(
    lines: list[Line], body_size: float
) -> tuple[list[Section], str, list[str]]:
    """Try each strategy in order and return the first whose output holds up.

    Text patterns are preferred over font even where both work: they survive a
    re-export, a different PDF producer, and a copy-paste into markdown, while
    font sizes do not.

    Each candidate is checked for quality, not just quantity. A method that
    produces many sections of nothing is worse than no method at all, because it
    reaches the index looking like success.
    """
    rejected: list[str] = []

    for name, indices in (
        ("text", headings_by_text(lines)),
        ("font", headings_by_font(lines, body_size)),
    ):
        if len(indices) < MIN_USEFUL_SECTIONS:
            continue
        sections = drop_empty_sections(split_into_sections(lines, indices))
        problems = quality_problems(sections)
        if not problems:
            return sections, name, rejected
        rejected.append(f"{name}: {'; '.join(problems)}")

    return [], "none", rejected


# --------------------------------------------------------------------------


def looks_like_slides(lines: list[Line], pages: int) -> bool:
    """Is this a presentation wearing a PDF costume?

    Two signals together, because either alone has false positives: a policy
    document can have an agenda, and a dense one can have short pages.
    """
    text = " ".join(line.text for line in lines).lower()
    marker_hits = sum(1 for marker in SLIDE_MARKERS if marker in text)
    chars_per_page = len(text) / pages if pages else 0
    return marker_hits >= 2 and chars_per_page < 900


def parse(path: Path) -> ParsedDocument:
    doc = ParsedDocument(path=path, title=path.stem.replace("-", " ").replace("_", " "))
    doc.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()[:12]

    try:
        with pdfplumber.open(path) as pdf:
            doc.pages = len(pdf.pages)
            doc.title = (pdf.metadata or {}).get("Title") or doc.title
            doc.tables = sum(len(page.find_tables()) for page in pdf.pages)
            lines, body_size = extract_lines(pdf)
    except Exception as exc:
        doc.warnings.append(f"unreadable: {type(exc).__name__}: {exc}")
        return doc

    doc.review_date = find_review_date(" ".join(line.text for line in lines))

    if looks_like_slides(lines, doc.pages):
        doc.warnings.append("not a policy: reads as a slide deck")
        return doc

    doc.sections, doc.heading_method, rejected = recover_sections(lines, body_size)

    if doc.heading_method == "none":
        doc.warnings.append("no structure: could not find headings by text or font")
        doc.warnings.extend(f"  rejected {r}" for r in rejected)
    if doc.tables:
        doc.warnings.append(f"{doc.tables} tables, flattened to text")
    if not doc.review_date:
        doc.warnings.append("no review date, staleness cannot be enforced")

    return doc


def to_markdown(doc: ParsedDocument) -> str:
    """Render as the markdown shape src/rag/chunking.py already handles.

    The point of converting rather than teaching the chunker about PDFs is that
    every measurement from week 2 keeps applying. A document that reaches this
    function is one the pipeline understood.
    """
    header = f"# {doc.title}\n\n"
    meta = f"**Source:** {doc.path.name} · **Last reviewed:** {doc.review_date or 'unknown'}\n\n"
    body = "\n\n".join(f"## {s.heading}\n\n{s.text}" for s in doc.sections if s.text)
    return header + meta + body + "\n"


def main() -> None:
    args = sys.argv[1:]
    if not args:
        console.print(__doc__)
        raise SystemExit(1)

    folder = Path(args[0])
    write_to = Path(args[args.index("--write") + 1]) if "--write" in args else None

    docs = [parse(path) for path in sorted(folder.glob("*.pdf"))]

    header = f"{'document':<44}{'method':>8}{'sections':>10}{'usable':>8}"
    console.print(f"\n[bold]{len(docs)} documents[/bold]\n")
    console.print(header)
    console.print("-" * len(header))
    for doc in docs:
        mark = "[green]yes[/green]" if doc.usable else "[red]no[/red]"
        console.print(
            f"{doc.path.name[:42]:<44}{doc.heading_method:>8}{len(doc.sections):>10}"
            f"{mark:>18}"
        )

    console.print("\n[bold]Warnings[/bold]")
    for doc in docs:
        if doc.warnings:
            console.print(f"\n  [cyan]{doc.path.name}[/cyan]")
            for warning in doc.warnings:
                console.print(f"    - {warning}")

    if write_to:
        write_to.mkdir(parents=True, exist_ok=True)
        written = 0
        for doc in docs:
            if not doc.usable or not doc.sections:
                continue
            (write_to / f"{doc.path.stem}.md").write_text(
                to_markdown(doc), encoding="utf-8"
            )
            written += 1
        console.print(f"\nwrote {written} of {len(docs)} documents to {write_to}")
        skipped = [d.path.name for d in docs if not d.usable or not d.sections]
        if skipped:
            console.print("[yellow]skipped:[/yellow] " + ", ".join(skipped))


if __name__ == "__main__":
    main()
