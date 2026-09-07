"""The control ontology: entities and the relationships between them, in SQLite.

    python -m src.ontology.store load

An ontology is not a dictionary. `src/agent/tools.py` has a dictionary -- eight
NIST controls with a title and a description, enough to look one up. What it
cannot answer is any question about how things relate:

    which controls has this company got no policy for?
    this answer cites a policy section -- which controls does that section
      satisfy, and which questionnaire questions does that make it serve?
    the buyer asked a SOC 2 question; which NIST control answers it?

Those are relationship questions, and they need edges, not rows.

    Question --asks_about--> Control --satisfied_by--> PolicySection
                               |
                        crosswalks_to
                               |
                               v
                       SOC 2 Criterion

Storage is SQLite with five tables. Not a graph database: at 1,196 controls and
a few thousand edges, every query here is one or two joins, and the traversals
are shallow. A graph database earns its place on deep multi-hop traversal or
when relationships outnumber entities by a lot -- see ADR-0013.

Loading the catalog costs nothing. No model is called.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

console = Console()

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "ontology" / "ontology.sqlite"
CATALOG_PATH = REPO_ROOT / "data" / "ontology" / "nist_800-53_rev5_catalog.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS control_family (
    id      TEXT PRIMARY KEY,   -- 'ac'
    title   TEXT NOT NULL       -- 'Access Control'
);

CREATE TABLE IF NOT EXISTS control (
    id          TEXT PRIMARY KEY,   -- 'ac-2' or 'ac-2.1' for an enhancement
    family_id   TEXT NOT NULL REFERENCES control_family(id),
    label       TEXT NOT NULL,      -- 'AC-2', the form a human writes
    title       TEXT NOT NULL,
    statement   TEXT NOT NULL,      -- what the control actually requires
    -- An enhancement (ac-2.1) is a stricter variant of its base control. Kept
    -- as a self-reference rather than a flag so "show me AC-2 and everything
    -- under it" is one query.
    parent_id   TEXT REFERENCES control(id)
);

-- One row per '## section' of one policy document. Deliberately not a copy of
-- the vector index: this table answers "what do we have policy for", which is a
-- question about coverage, not similarity.
CREATE TABLE IF NOT EXISTS policy_section (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,      -- filename
    section     TEXT NOT NULL,      -- heading
    text        TEXT NOT NULL,
    review_date TEXT,               -- staleness: a 2018 policy is not evidence
    UNIQUE (source, section)
);

-- The edge that makes this an ontology. `confidence` and `confirmed_by` exist
-- because these links are proposed by a machine and must be accepted by a
-- person before anyone relies on them in an audit.
CREATE TABLE IF NOT EXISTS satisfies (
    control_id  TEXT NOT NULL REFERENCES control(id),
    section_id  INTEGER NOT NULL REFERENCES policy_section(id),
    confidence  REAL NOT NULL,
    method      TEXT NOT NULL,      -- 'embedding' | 'human'
    confirmed_by TEXT,              -- NULL until a person accepts it
    PRIMARY KEY (control_id, section_id)
);

-- NIST control to another framework's criterion. The payoff: answer a question
-- once against a control, and it serves a SOC 2 questionnaire and a NIST one.
CREATE TABLE IF NOT EXISTS crosswalk (
    control_id  TEXT NOT NULL REFERENCES control(id),
    framework   TEXT NOT NULL,      -- 'SOC2'
    criterion   TEXT NOT NULL,      -- 'CC6.1'
    note        TEXT,
    PRIMARY KEY (control_id, framework, criterion)
);

CREATE INDEX IF NOT EXISTS idx_control_family ON control(family_id);
CREATE INDEX IF NOT EXISTS idx_satisfies_section ON satisfies(section_id);
CREATE INDEX IF NOT EXISTS idx_crosswalk_criterion ON crosswalk(framework, criterion);
"""


@dataclass(frozen=True)
class Control:
    id: str
    family_id: str
    label: str
    title: str
    statement: str
    parent_id: str | None


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _prose(part: dict) -> str:
    """Flatten an OSCAL part into readable text.

    A control statement is a tree: a lead-in sentence with lettered items under
    it, each of which may have numbered items under that. Losing the nesting
    costs nothing here -- the statement is used for matching and for display,
    not for compliance logic.
    """
    pieces = [part.get("prose", "")]
    for child in part.get("parts", []):
        pieces.append(_prose(child))
    return " ".join(p for p in pieces if p).strip()


def _statement(control: dict) -> str:
    for part in control.get("parts", []):
        if part.get("name") == "statement":
            return _prose(part)
    return control.get("title", "")


def _label(control: dict) -> str:
    for prop in control.get("props", []):
        if prop.get("name") == "label":
            return prop["value"]
    return control["id"].upper()


def walk_controls(
    controls: list[dict], family_id: str, parent_id: str | None = None
) -> list[Control]:
    """Flatten the OSCAL tree, keeping the parent link for enhancements."""
    out: list[Control] = []
    for raw in controls:
        control = Control(
            id=raw["id"],
            family_id=family_id,
            label=_label(raw),
            title=raw["title"],
            statement=_statement(raw),
            parent_id=parent_id,
        )
        out.append(control)
        out.extend(walk_controls(raw.get("controls", []), family_id, control.id))
    return out


def load_catalog(conn: sqlite3.Connection, catalog_path: Path | None = None) -> int:
    """Load NIST SP 800-53 from its OSCAL JSON.

    OSCAL is NIST's own machine-readable format for the catalog, so this is the
    authoritative source rather than a scraped table. It also means the version
    is recorded in the file, which matters: an answer mapped to a Rev 5 control
    is not necessarily mapped to the same thing in Rev 4.
    """
    catalog = json.loads((catalog_path or CATALOG_PATH).read_text(encoding="utf-8"))[
        "catalog"
    ]

    families = [(g["id"], g["title"]) for g in catalog.get("groups", [])]
    conn.executemany(
        "INSERT OR REPLACE INTO control_family (id, title) VALUES (?, ?)", families
    )

    controls: list[Control] = []
    for group in catalog.get("groups", []):
        controls.extend(walk_controls(group.get("controls", []), group["id"]))

    conn.executemany(
        "INSERT OR REPLACE INTO control "
        "(id, family_id, label, title, statement, parent_id) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (c.id, c.family_id, c.label, c.title, c.statement, c.parent_id)
            for c in controls
        ],
    )
    conn.commit()
    return len(controls)


def load_policy_sections(conn: sqlite3.Connection, corpus_dir: Path) -> int:
    """Load the parsed corpus, one row per markdown section."""
    import re

    rows: list[tuple[str, str, str, str | None]] = []
    for path in sorted(corpus_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        date_match = re.search(r"\*\*Last reviewed:\*\* (.+?)\n", text)
        review_date = date_match.group(1).strip() if date_match else None
        matches = list(re.finditer(r"^## (.+)$", text, re.MULTILINE))
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[match.end() : end].strip()
            if body:
                rows.append((path.name, match.group(1).strip(), body, review_date))

    conn.executemany(
        "INSERT OR REPLACE INTO policy_section (source, section, text, review_date) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "load"
    conn = connect()

    if command == "load":
        controls = load_catalog(conn)
        corpus = REPO_ROOT / "data" / "policies_real"
        sections = load_policy_sections(conn, corpus) if corpus.exists() else 0

        families = conn.execute("SELECT COUNT(*) FROM control_family").fetchone()[0]
        base = conn.execute(
            "SELECT COUNT(*) FROM control WHERE parent_id IS NULL"
        ).fetchone()[0]
        console.print(f"families          {families}")
        console.print(f"base controls     {base}")
        console.print(f"with enhancements {controls}")
        console.print(f"policy sections   {sections}")
        console.print(f"database          {DB_PATH}")
    else:
        console.print(__doc__)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
