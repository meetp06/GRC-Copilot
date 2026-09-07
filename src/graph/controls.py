"""Map a finished answer to the controls its cited sections satisfy.

The ontology already knows which controls each policy section satisfies. An
answer already knows which sections it cited. Joining those two is what turns
"here is your answer with a citation" into "here is your answer, the section it
came from, the NIST controls that section satisfies, and the SOC 2 criteria
those controls serve".

That is the product claim: answer once, serve every framework the buyer asks in.

Nothing here calls a model. It is two queries against data already built.
"""

from __future__ import annotations

from src.graph.state import QuestionState
from src.ontology.store import connect


def controls_for(state: QuestionState) -> dict:
    """Controls and SOC 2 criteria reachable from this answer's citations.

    Only cited sections count, not everything retrieved. A control reached
    through a passage the drafter did not use is not evidenced by this answer.
    """
    retrieved = state.get("retrieved", [])
    cited = [
        retrieved[i - 1] for i in state.get("citations", []) if 1 <= i <= len(retrieved)
    ]
    if not cited:
        return {"controls": [], "soc2": [], "unconfirmed": 0}

    conn = connect()
    pairs = [(c["source"], c["section"]) for c in cited]
    # Only "?" markers, one pair per cited section. The values are bound, never
    # interpolated -- SQLite has no syntax for a variable-length parameter list,
    # so the marker count has to be built into the string. (nosec B608 below.)
    placeholders = ",".join("(?,?)" for _ in pairs)
    flat = [v for pair in pairs for v in pair]

    rows = conn.execute(
        f"""
        SELECT DISTINCT c.label, c.title, s.confidence, s.confirmed_by
        FROM policy_section p
        JOIN satisfies s ON s.section_id = p.id
        JOIN control c ON c.id = s.control_id
        WHERE (p.source, p.section) IN (VALUES {placeholders})
        ORDER BY s.confidence DESC
        """,  # nosec B608
        flat,
    ).fetchall()

    labels = [r["label"] for r in rows]
    soc2 = (
        [
            r["criterion"]
            for r in conn.execute(
                f"""
                SELECT DISTINCT x.criterion
                FROM policy_section p
                JOIN satisfies s ON s.section_id = p.id
                JOIN crosswalk x ON x.control_id = s.control_id
                WHERE (p.source, p.section) IN (VALUES {placeholders})
                ORDER BY x.criterion
                """,  # nosec B608
                flat,
            ).fetchall()
        ]
        if labels
        else []
    )

    return {
        "controls": [
            {
                "label": r["label"],
                "title": r["title"],
                "confidence": r["confidence"],
                "confirmed": bool(r["confirmed_by"]),
            }
            for r in rows
        ],
        "soc2": soc2,
        # Surfaced, not hidden: an unconfirmed mapping is a machine's opinion,
        # and an answer resting on one should not read as audited fact.
        "unconfirmed": sum(1 for r in rows if not r["confirmed_by"]),
    }
