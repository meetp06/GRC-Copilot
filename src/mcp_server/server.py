"""MCP server: use GRC Copilot from inside Claude, Cursor, or any MCP client.

    python -m src.mcp_server.server

    // claude_desktop_config.json
    {"mcpServers": {"grc-copilot": {
        "command": "/path/to/.venv/bin/python",
        "args": ["-m", "src.mcp_server.server"],
        "cwd": "/path/to/grc-copilot"
    }}}

MCP (Model Context Protocol) is a standard way to hand a model a set of tools.
The client -- Claude Desktop, Cursor -- starts this process, asks what tools it
has, and calls them when the conversation needs one. It is the same
schema-and-callable pairing as `src/agent/tools.py` in week 1, with the
transport standardised so any client can use it.

Why this and not just the HTTP API: an analyst filling in a questionnaire is
already in a chat window. Asking there and getting an answer with its citation
beats switching to a web app, and it means the ontology and the corpus are
available in the middle of a conversation rather than as a separate errand.

    analyst asks in chat ─▶ answer_question ─▶ answer + citation + controls
                         ↘ find_policy      ─▶ what the corpus actually says
                         ↘ control_coverage ─▶ what we have no policy for

This calls the graph in-process rather than over HTTP, so it works with no
server running. The cost is that it holds its own vector index; the benefit is
that "clone the repo, point Claude at it" is the whole setup.

Every tool returns citations. A tool that returned a bare answer would let a
model repeat a policy claim with nothing behind it, which is the failure this
whole product exists to prevent.
"""

from __future__ import annotations

import json
from typing import Any

# mcp 2.x renamed FastMCP to MCPServer. Importing the old name fails outright
# rather than degrading, which is the right behaviour for a transport library.
from mcp.server.mcpserver import MCPServer

from src.graph.build import build_graph
from src.graph.controls import controls_for
from src.ontology.store import connect as ontology_connect
from src.rag.index import VectorIndex

mcp = MCPServer("grc-copilot", version="0.5.0")

INDEX_NAME = "real"
_index: VectorIndex | None = None
_graph = None


def _get_graph():
    """Build the graph once. Loading per call would re-read the index each time."""
    global _index, _graph
    if _graph is None:
        _index = VectorIndex.load(INDEX_NAME)
        _graph = build_graph(_index)
    return _graph


@mcp.tool()
def answer_question(question: str) -> str:
    """Answer a security questionnaire question from the company's policy corpus.

    Returns the answer, the policy sections it cites, the NIST 800-53 controls
    those sections satisfy, and the SOC 2 criteria they serve. If the corpus
    does not cover the question, `answerable` is false and no answer is invented
    -- refusing is the correct outcome, not a failure.

    Use this for questions a buyer would ask in a security review: encryption,
    access control, incident response, data retention, vendor management.
    """
    state = _get_graph().invoke(
        {"question": question, "question_id": "mcp", "status": "retrieving"}
    )
    retrieved = state.get("retrieved", [])
    mapped = controls_for(state)

    return json.dumps(
        {
            "answerable": state.get("answerable"),
            "answer": state.get("draft"),
            "confidence": state.get("confidence"),
            "verified": state.get("verified"),
            "citations": [
                {
                    "source": retrieved[i - 1]["source"],
                    "section": retrieved[i - 1]["section"],
                }
                for i in state.get("citations", [])
                if 1 <= i <= len(retrieved)
            ],
            "nist_controls": [c["label"] for c in mapped["controls"]],
            "soc2_criteria": mapped["soc2"],
            # Stated, not hidden. A control mapping nobody has confirmed is a
            # machine's opinion, and a model reading this should not present it
            # as an audited fact.
            "unconfirmed_control_mappings": mapped["unconfirmed"],
        },
        indent=2,
    )


@mcp.tool()
def find_policy(query: str, top_k: int = 3) -> str:
    """Search the policy corpus and return the matching passages verbatim.

    Use this when the exact wording matters -- drafting a response, checking
    what a policy actually says, or confirming a claim before repeating it.
    Unlike answer_question, this does not summarise: it returns source text.
    """
    _get_graph()
    hits = _index.search(query, top_k=max(1, min(top_k, 10)))
    return json.dumps(
        [
            {
                "source": h.source,
                "section": h.section,
                "similarity": round(h.score, 3),
                "text": h.text,
            }
            for h in hits
        ],
        indent=2,
    )


@mcp.tool()
def lookup_control(label: str) -> str:
    """Look up a NIST 800-53 control and what policy satisfies it.

    Accepts the label as a person writes it: AC-2, SC-28, IR-4. Returns the
    control statement, the policy sections claimed to satisfy it, whether a
    human has confirmed each of those claims, and the SOC 2 criteria it
    crosswalks to.
    """
    conn = ontology_connect()
    # Catalog labels are zero-padded (AC-02); people write AC-2.
    normalised = label.strip().upper().replace(" ", "")
    row = conn.execute(
        "SELECT id, label, title, statement FROM control "
        "WHERE upper(label) = ? OR upper(replace(label, '-0', '-')) = ?",
        (normalised, normalised),
    ).fetchone()
    if row is None:
        return json.dumps({"error": f"no control matching {label!r}"})

    sections = conn.execute(
        """
        SELECT p.source, p.section, s.confidence, s.confirmed_by
        FROM satisfies s JOIN policy_section p ON p.id = s.section_id
        WHERE s.control_id = ? ORDER BY s.confidence DESC
        """,
        (row["id"],),
    ).fetchall()
    criteria = [
        r["criterion"]
        for r in conn.execute(
            "SELECT DISTINCT criterion FROM crosswalk WHERE control_id = ? ORDER BY criterion",
            (row["id"],),
        )
    ]

    return json.dumps(
        {
            "label": row["label"],
            "title": row["title"],
            "statement": row["statement"][:1200],
            "soc2_criteria": criteria,
            "satisfied_by": [
                {
                    "source": s["source"],
                    "section": s["section"],
                    "confidence": round(s["confidence"], 3),
                    "confirmed_by": s["confirmed_by"],
                }
                for s in sections
            ],
        },
        indent=2,
    )


@mcp.tool()
def control_coverage(family: str | None = None) -> str:
    """Report which NIST controls have no supporting policy.

    This is the gap analysis: what a customer would have to write policy for
    before claiming coverage. Pass a family name such as 'Access Control' to
    narrow it, or leave it empty for a summary across all 20 families.
    """
    conn = ontology_connect()
    if family:
        rows = conn.execute(
            """
            SELECT c.label, c.title
            FROM control c JOIN control_family f ON f.id = c.family_id
            WHERE c.parent_id IS NULL AND lower(f.title) LIKE lower(?)
              AND NOT EXISTS (SELECT 1 FROM satisfies s WHERE s.control_id = c.id)
            ORDER BY c.label
            """,
            (f"%{family}%",),
        ).fetchall()
        return json.dumps(
            {
                "family": family,
                "controls_without_policy": [
                    {"label": r["label"], "title": r["title"]} for r in rows
                ],
            },
            indent=2,
        )

    rows = conn.execute(
        """
        SELECT f.title AS family, COUNT(*) AS missing
        FROM control c JOIN control_family f ON f.id = c.family_id
        WHERE c.parent_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM satisfies s WHERE s.control_id = c.id)
        GROUP BY f.title ORDER BY missing DESC
        """
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) FROM control WHERE parent_id IS NULL"
    ).fetchone()[0]
    return json.dumps(
        {
            "controls_total": total,
            "controls_without_policy": sum(r["missing"] for r in rows),
            "by_family": [
                {"family": r["family"], "missing": r["missing"]} for r in rows
            ],
        },
        indent=2,
    )


def tool_names() -> list[str]:
    """The tool names this server exposes. Used by the tests."""
    return ["answer_question", "find_policy", "lookup_control", "control_coverage"]


def main() -> Any:
    from dotenv import load_dotenv

    load_dotenv()
    mcp.run()


if __name__ == "__main__":
    main()
