"""Graph nodes. Each one reads QuestionState and returns only the keys it changed.

Day 1 is a port, not a redesign: `retrieve` and `draft` do exactly what
src/rag/index.py and src/rag/answer.py already did, so the week 2 eval numbers
have to come out identical. Anything that moves is a bug I introduced.

Nodes take their dependencies (the vector index, the model id) from a closure
rather than from state, because state is serialised to SQLite at every step and
a boto3 client cannot be written to a database.
"""

from __future__ import annotations

from collections.abc import Callable

from src.rag.answer import answer_question
from src.rag.index import VectorIndex
from src.graph.state import QuestionState, RetrievedChunk

TOP_K = 5


def make_retrieve(
    index: VectorIndex, top_k: int = TOP_K
) -> Callable[[QuestionState], dict]:
    """Search the policy corpus and put the passages into state.

    Retrieval is its own node rather than part of drafting so that the verifier
    and the human reviewer can both see exactly what the drafter was shown. A
    citation nobody can trace back to a passage is not a citation.
    """

    def retrieve(state: QuestionState) -> dict:
        hits = index.search(state["question"], top_k=top_k)
        retrieved: list[RetrievedChunk] = [
            {"source": h.source, "section": h.section, "text": h.text, "score": h.score}
            for h in hits
        ]
        return {"retrieved": retrieved, "status": "drafting"}

    return retrieve


def make_draft(
    index: VectorIndex, model_id: str | None = None
) -> Callable[[QuestionState], dict]:
    """Ask the model for an answer, with the shape forced by a tool schema.

    Calls answer_question unchanged, which re-runs retrieval internally. That is
    knowingly wasteful -- one extra embedding call per question, about $0.000002
    -- and it is the price of day 1 being a provable port rather than a rewrite.
    Day 2 splits answer_question so the drafter consumes state["retrieved"].
    """

    def draft(state: QuestionState) -> dict:
        result = answer_question(state["question"], index, model_id=model_id)
        return {
            "answerable": result.answerable,
            "draft": result.answer,
            "citations": result.citations,
            "model_confidence": result.confidence,
            "confidence": result.confidence,
            "status": "approved" if result.answerable else "needs_review",
            "input_tokens": state.get("input_tokens", 0) + result.input_tokens,
            "output_tokens": state.get("output_tokens", 0) + result.output_tokens,
            "revision_count": state.get("revision_count", 0),
            "verified": False,
            "critique": None,
        }

    return draft
