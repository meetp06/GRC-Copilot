"""Survey a folder of real documents before parsing any of them.

    python -m src.pipeline.inventory data/raw

Week 1 to 3 ran on twelve markdown files with clean `##` headings, written to be
easy. Real customers hand over a folder of PDFs, and the first honest question is
not "how do I parse this" but "what am I actually holding".

So this reads every document and reports what is wrong with it. It deliberately
does not parse, chunk, embed or fix anything. Knowing that three of thirty files
are scans is worth more right now than a parser built on a guess about which
ones they are.

What it checks, and why each one changes what has to be built:

  text or scan       A scan yields almost no characters per page and needs OCR,
                     which is a system binary and a quality cliff, not a pip
                     install. Nothing else about the pipeline matters until this
                     is known for every file.

  heading structure  ADR-0005 chose section-aware chunking because policy
                     documents carry a human-curated segmentation in their
                     headings. A PDF with no detectable headings is that ADR
                     meeting reality.

  tables             A control matrix flattened to a line of text loses the
                     mapping it exists to express.

  review date        A policy last reviewed in 2019 should not be cited as
                     current evidence to an auditor. That is a product
                     requirement, not a parsing detail, and the date has to
                     survive ingestion for it to be enforceable later.

Costs nothing. No model is called.
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
from rich.console import Console

console = Console()

# Below this many characters per page, a PDF is almost certainly a scan: the
# page is an image and the text layer is empty or near it. A native-text policy
# document runs into the thousands.
SCAN_THRESHOLD_CHARS_PER_PAGE = 100

# A heading, in a PDF that has lost its structure, is a short line that is not a
# sentence. Numbered ("4.2 Access Control"), all-caps, or title case without
# terminal punctuation. Crude on purpose -- the point is to find out whether
# anything heading-shaped survives, not to parse perfectly.
HEADING_PATTERNS = [
    re.compile(r"^\s*\d+(\.\d+)*\.?\s+[A-Z][^.!?]{2,60}$"),  # 4.2 Access Control
    # Roman numerals. The first version of this list required digits, and
    # reported "no detectable headings" for a document whose headings were
    # I. Purpose / II. Scope / III. Definitions. The tool was wrong, not the
    # document -- and the wrong answer pointed at rebuilding structure from font
    # data, which is far more work than adding a pattern.
    re.compile(r"^\s*[IVXLC]+\.\s+[A-Z][^.!?]{2,60}$"),  # III. Definitions
    re.compile(r"^\s*[A-Z][A-Z\s&/-]{4,60}$"),  # ACCEPTABLE USE
    re.compile(r"^\s*(?:Section|Article|Appendix)\s+\w+", re.IGNORECASE),
    re.compile(r"^\s*[A-Z]\.\s+[A-Z][^.!?]{2,60}$"),  # B. Responsibilities
]

DATE_PATTERNS = [
    re.compile(
        r"(?:last\s+)?(?:reviewed|revised|updated|effective|approved)[\s:]*"
        r"([A-Z][a-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:reviewed|revised|updated|effective)[\s:]*.{0,20}?(20\d{2})", re.IGNORECASE
    ),
]


@dataclass
class DocumentReport:
    path: Path
    pages: int = 0
    chars: int = 0
    headings: int = 0
    tables: int = 0
    title: str | None = None
    review_date: str | None = None
    sha256: str = ""
    problems: list[str] = field(default_factory=list)

    @property
    def chars_per_page(self) -> float:
        return self.chars / self.pages if self.pages else 0.0

    @property
    def is_scan(self) -> bool:
        return self.pages > 0 and self.chars_per_page < SCAN_THRESHOLD_CHARS_PER_PAGE


def looks_like_heading(line: str) -> bool:
    line = line.strip()
    if not (3 < len(line) < 80):
        return False
    if line.endswith((".", "!", "?", ",", ";", ":")):
        return False
    return any(pattern.match(line) for pattern in HEADING_PATTERNS)


def find_review_date(text: str) -> str | None:
    """The most recent date the document claims it was reviewed.

    Takes the first match rather than the newest: policy documents put the
    review date in the header or footer, and a date deeper in the body is more
    likely to belong to something else.
    """
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


def inspect(path: Path) -> DocumentReport:
    report = DocumentReport(path=path)
    report.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()[:12]

    try:
        with pdfplumber.open(path) as pdf:
            report.pages = len(pdf.pages)
            report.title = (pdf.metadata or {}).get("Title") or None

            text_parts: list[str] = []
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
                report.tables += len(page.find_tables())
            text = "\n".join(text_parts)
    except Exception as exc:  # a corrupt file is a finding, not a crash
        report.problems.append(f"unreadable: {type(exc).__name__}")
        return report

    report.chars = len(text)
    report.headings = sum(1 for line in text.splitlines() if looks_like_heading(line))
    report.review_date = find_review_date(text)

    if report.is_scan:
        report.problems.append("scanned or image-only, needs OCR")
    if report.headings == 0 and not report.is_scan:
        report.problems.append("no detectable headings, section chunking will not work")
    if report.tables:
        report.problems.append(f"{report.tables} tables, flattening loses them")
    if report.pages > 40:
        report.problems.append(f"{report.pages} pages, long")
    if not report.review_date:
        report.problems.append("no review date found, staleness unenforceable")
    if not report.title:
        report.problems.append("no title in metadata")

    return report


def main() -> None:
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "data/raw")
    paths = sorted(folder.glob("*.pdf"))
    if not paths:
        console.print(f"[yellow]no PDFs in {folder}[/yellow]")
        raise SystemExit(1)

    reports = [inspect(path) for path in paths]

    header = f"{'document':<44}{'pages':>6}{'ch/page':>9}{'head':>6}{'tbl':>5}  {'reviewed':<12}"
    console.print(f"\n[bold]{len(reports)} documents in {folder}[/bold]\n")
    console.print(header)
    console.print("-" * len(header))
    for r in reports:
        name = r.path.name[:42]
        console.print(
            f"{name:<44}{r.pages:>6}{r.chars_per_page:>9.0f}{r.headings:>6}"
            f"{r.tables:>5}  {(r.review_date or '-'):<12}"
        )

    console.print("\n[bold]Problems[/bold]")
    clean = True
    for r in reports:
        if r.problems:
            clean = False
            console.print(f"\n  [cyan]{r.path.name}[/cyan]")
            for problem in r.problems:
                console.print(f"    - {problem}")
    if clean:
        console.print("  none")

    scans = [r for r in reports if r.is_scan]
    headless = [r for r in reports if not r.is_scan and r.headings == 0]
    undated = [r for r in reports if not r.review_date]
    console.print(
        f"\n[bold]Summary[/bold]  {len(scans)} need OCR, {len(headless)} have no headings, "
        f"{len(undated)} have no review date"
    )


if __name__ == "__main__":
    main()
