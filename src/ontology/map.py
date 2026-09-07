"""Propose which controls each policy section satisfies, and report the gaps.

    python -m src.ontology.map propose      # embed and link, ~$0.002
    python -m src.ontology.map gaps         # which controls have no policy
    python -m src.ontology.map coverage     # per family
    python -m src.ontology.map confirm ac-2 12 --by meet

Mapping is done by embedding, then confirmed by a person. Both halves matter:

  A machine can read 324 control statements against 41 policy sections in
  seconds, which no analyst is going to do by hand for every corpus.

  A machine cannot be the reason a control is marked satisfied. That claim goes
  into an audit, and "an embedding said 0.61" is not a basis for it. So every
  proposed edge lands unconfirmed, and `confirmed_by` stays NULL until a named
  person accepts it.

Only base controls are matched, not the 872 enhancements. An enhancement is a
stricter variant of its parent -- AC-2(1) is "automate account management" -- and
a policy section that satisfies the parent says nothing about whether the
stricter version is met. Proposing those links would manufacture coverage.

The gap report is the part a customer pays for, and it is one query: controls
with no confirmed edge. That report is why this is a database and not a
dictionary.
"""

from __future__ import annotations

import sqlite3
import sys

import numpy as np
from rich.console import Console

from src.ontology.store import connect
from src.rag.embeddings import embed_texts

console = Console()

# Below this cosine similarity a proposal is noise. Calibrated against the
# observed range: real matches here run 0.45-0.70, and everything under 0.40 was
# a control and a section that merely share compliance vocabulary.
MIN_CONFIDENCE = 0.40

# How many controls to propose per section. A policy section genuinely satisfies
# a handful of controls; proposing twenty would bury the real ones and make the
# human confirmation step useless.
TOP_CONTROLS_PER_SECTION = 5


def base_controls(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Base controls only. Enhancements are excluded -- see the module docstring."""
    return conn.execute(
        "SELECT id, label, title, statement FROM control "
        "WHERE parent_id IS NULL ORDER BY id"
    ).fetchall()


def propose(conn: sqlite3.Connection) -> int:
    """Embed every control and every policy section, and link the close pairs.

    Controls are embedded as 'label title. statement' so the label carries into
    the vector -- a section that literally says 'AC-2' should match AC-2 even
    when the prose does not line up.
    """
    controls = base_controls(conn)
    sections = conn.execute(
        "SELECT id, source, section, text FROM policy_section"
    ).fetchall()
    if not sections:
        console.print("[yellow]no policy sections loaded[/yellow]")
        return 0

    console.print(f"embedding {len(controls)} controls and {len(sections)} sections...")
    control_vectors = embed_texts(
        [f"{c['label']} {c['title']}. {c['statement']}"[:2000] for c in controls]
    )
    section_vectors = embed_texts(
        [f"{s['section']}. {s['text']}"[:2000] for s in sections]
    )
    cost = control_vectors.usd_cost + section_vectors.usd_cost

    # Unit vectors, so this matrix product is cosine similarity.
    scores = section_vectors.vectors @ control_vectors.vectors.T

    rows = []
    for si, section in enumerate(sections):
        best = np.argsort(-scores[si])[:TOP_CONTROLS_PER_SECTION]
        for ci in best:
            score = float(scores[si, ci])
            if score < MIN_CONFIDENCE:
                continue
            rows.append((controls[ci]["id"], section["id"], score, "embedding", None))

    conn.executemany(
        "INSERT OR REPLACE INTO satisfies "
        "(control_id, section_id, confidence, method, confirmed_by) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    console.print(f"proposed {len(rows)} edges, cost ${cost:.4f}")
    return len(rows)


def show_proposals(conn: sqlite3.Connection, limit: int = 20) -> None:
    rows = conn.execute(
        """
        SELECT c.label, c.title, p.source, p.section, s.confidence, s.confirmed_by
        FROM satisfies s
        JOIN control c ON c.id = s.control_id
        JOIN policy_section p ON p.id = s.section_id
        ORDER BY s.confidence DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    console.print(f"\n[bold]Top {len(rows)} proposed mappings[/bold]\n")
    for r in rows:
        mark = (
            "[green]confirmed[/green]"
            if r["confirmed_by"]
            else "[yellow]unconfirmed[/yellow]"
        )
        console.print(
            f"  {r['confidence']:.3f}  {r['label']:<7} {r['title'][:34]:<36} "
            f"<- {r['section'][:32]:<34} {mark}"
        )


def gaps(conn: sqlite3.Connection, confirmed_only: bool = False) -> None:
    """Controls with no policy section mapped to them.

    This is the report a customer pays for, and it is one query. `confirmed_only`
    is the honest version: an unconfirmed machine proposal is not coverage, so
    the gap list under that flag is always longer and always the real one.
    """
    clause = "AND s.confirmed_by IS NOT NULL" if confirmed_only else ""
    rows = conn.execute(
        f"""
        SELECT f.title AS family, COUNT(*) AS missing
        FROM control c
        JOIN control_family f ON f.id = c.family_id
        WHERE c.parent_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM satisfies s WHERE s.control_id = c.id {clause}
          )
        GROUP BY f.title ORDER BY missing DESC
        """
    ).fetchall()
    total_missing = sum(r["missing"] for r in rows)
    total = conn.execute(
        "SELECT COUNT(*) FROM control WHERE parent_id IS NULL"
    ).fetchone()[0]

    label = "confirmed" if confirmed_only else "proposed or confirmed"
    console.print(
        f"\n[bold]Gap analysis[/bold] ({label} coverage)\n"
        f"  {total_missing} of {total} base controls have no policy section\n"
    )
    for r in rows[:12]:
        console.print(f"  {r['missing']:>4}  {r['family']}")


def coverage(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT f.title AS family,
               COUNT(DISTINCT c.id) AS controls,
               COUNT(DISTINCT s.control_id) AS covered
        FROM control_family f
        JOIN control c ON c.family_id = f.id AND c.parent_id IS NULL
        LEFT JOIN satisfies s ON s.control_id = c.id
        GROUP BY f.title
        HAVING covered > 0
        ORDER BY covered DESC
        """
    ).fetchall()
    console.print("\n[bold]Families with any coverage[/bold]\n")
    console.print(f"  {'family':<40}{'covered':>9}{'of':>5}")
    for r in rows:
        console.print(f"  {r['family'][:38]:<40}{r['covered']:>9}{r['controls']:>5}")


def confirm(
    conn: sqlite3.Connection, control_id: str, section_id: int, by: str
) -> None:
    """Accept a proposed edge. The named person is the point."""
    cursor = conn.execute(
        "UPDATE satisfies SET confirmed_by = ?, method = 'human' "
        "WHERE control_id = ? AND section_id = ?",
        (by, control_id, section_id),
    )
    conn.commit()
    if cursor.rowcount:
        console.print(
            f"[green]{control_id} <- section {section_id} confirmed by {by}[/green]"
        )
    else:
        console.print(
            f"[yellow]no proposal for {control_id} / section {section_id}[/yellow]"
        )


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    command = sys.argv[1] if len(sys.argv) > 1 else "gaps"
    conn = connect()

    if command == "propose":
        propose(conn)
        show_proposals(conn)
    elif command == "show":
        show_proposals(conn, int(sys.argv[2]) if len(sys.argv) > 2 else 20)
    elif command == "gaps":
        gaps(conn, confirmed_only="--confirmed" in sys.argv)
    elif command == "coverage":
        coverage(conn)
    elif command == "confirm" and len(sys.argv) >= 4:
        by = sys.argv[sys.argv.index("--by") + 1] if "--by" in sys.argv else "unknown"
        confirm(conn, sys.argv[2], int(sys.argv[3]), by)
    else:
        console.print(__doc__)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
