"""Graph nodes. Each one reads QuestionState and returns only the keys it changed.

Nodes take their dependencies (the vector index, the model id) from a closure
rather than from state, because state is serialised to SQLite at every step and
a boto3 client cannot be written to a database.
"""

from __future__ import annotations

from collections.abc import Callable

from langgraph.types import interrupt

from src.graph.state import MAX_REVISIONS, QuestionState, RetrievedChunk
from src.rag.answer import draft_answer
from src.rag.index import VectorIndex
from src.rag.verify import verify_answer

TOP_K = 5


class _Hit:
    """Rebuilds the shape draft_answer expects from serialised state.

    State holds plain dicts so it survives the checkpointer; draft_answer takes
    objects with attributes. This adapter is the seam between the two.
    """

    def __init__(self, chunk: RetrievedChunk) -> None:
        self.source = chunk["source"]
        self.section = chunk["section"]
        self.text = chunk["text"]
        self.score = chunk["score"]


def make_retrieve(
    index: VectorIndex, top_k: int = TOP_K
) -> Callable[[QuestionState], dict]:
    """Search the policy corpus and put the passages into state.

    Retrieval is its own node so the verifier and the human reviewer can both
    see exactly what the drafter was shown. A citation nobody can trace back to
    a passage is not a citation.
    """

    def retrieve(state: QuestionState) -> dict:
        hits = index.search(state["question"], top_k=top_k)
        retrieved: list[RetrievedChunk] = [
            {"source": h.source, "section": h.section, "text": h.text, "score": h.score}
            for h in hits
        ]
        return {
            "retrieved": retrieved,
            "status": "drafting",
            "revision_count": 0,
            "verified": False,
            "critique": None,
        }

    return retrieve


def make_draft(model_id: str | None = None) -> Callable[[QuestionState], dict]:
    """Write an answer from the passages already in state.

    Reads state["retrieved"] rather than retrieving again. On a retry the
    verifier's critique is in state, and passing it here is what makes the
    second attempt different from the first -- without it the loop would redraft
    identically at temperature 0 and burn its revisions for nothing.
    """

    def draft(state: QuestionState) -> dict:
        hits = [_Hit(c) for c in state["retrieved"]]
        result = draft_answer(
            state["question"],
            hits,
            model_id=model_id,
            critique=state.get("critique"),
        )
        return {
            "answerable": result.answerable,
            "draft": result.answer,
            "citations": result.citations,
            "model_confidence": result.confidence,
            "status": "verifying",
            "input_tokens": state.get("input_tokens", 0) + result.input_tokens,
            "output_tokens": state.get("output_tokens", 0) + result.output_tokens,
        }

    return draft


def make_verify(model_id: str | None = None) -> Callable[[QuestionState], dict]:
    """Check the draft against the passages it cited.

    A refusal is not checked. There is no claim to support, and asking a
    verifier to confirm the absence of evidence invites it to argue the answer
    back into existence. It also saves a model call on every refusal.
    """

    def verify(state: QuestionState) -> dict:
        if not state.get("answerable", False):
            return {"verified": True, "critique": None}

        cited = [
            state["retrieved"][i - 1]
            for i in state.get("citations", [])
            if 1 <= i <= len(state["retrieved"])
        ]
        verdict = verify_answer(
            state["question"], state["draft"], cited, model_id=model_id
        )
        return {
            "verified": verdict.supported,
            "critique": None if verdict.supported else verdict.critique,
            "revision_count": state.get("revision_count", 0)
            + (0 if verdict.supported else 1),
            "input_tokens": state.get("input_tokens", 0) + verdict.input_tokens,
            "output_tokens": state.get("output_tokens", 0) + verdict.output_tokens,
        }

    return verify


def route_after_verify(state: QuestionState) -> str:
    """Decide where a verified (or rejected) draft goes next.

    Three outcomes, and the bound is the important one. Without a cap on
    revision_count the drafter and verifier rewrite and reject each other until
    the token budget is gone -- the week 1 runaway failure, one level up between
    two agents instead of inside one loop. The counter lives in state and no
    model can see or change it.
    """
    if state.get("verified"):
        return "accept"
    if state.get("revision_count", 0) >= MAX_REVISIONS:
        return "give_up"
    return "retry"


def finalise(state: QuestionState) -> dict:
    """Set the terminal status a human or a batch report reads.

    Only a verified, answerable draft is auto-approved. Everything else waits
    for a person: a refusal, a draft the verifier would not pass, and a draft
    that ran out of revisions. In a compliance product the safe default is a
    queue, not a send.
    """
    if not state.get("answerable", False):
        return {"status": "needs_review", "confidence": "low"}
    if not state.get("verified", False):
        return {"status": "needs_review", "confidence": "low"}
    return {
        "status": "approved",
        "confidence": state.get("model_confidence", "medium"),
    }


def human_review(state: QuestionState) -> dict:
    """Stop the graph and wait for a person.

    `interrupt()` raises out of the graph. LangGraph has already checkpointed
    everything up to this point, so the process can exit, crash, or be killed
    and the run resumes here later with no work repeated.

    The dict passed to interrupt() is what the reviewer sees. It carries the
    draft, the citations resolved to real document sections, and the verifier's
    complaint if there was one -- everything needed to decide without opening
    the corpus.

    Resuming supplies a decision, which becomes this call's return value:

        Command(resume={"action": "approve"})
        Command(resume={"action": "edit", "answer": "..."})
        Command(resume={"action": "reject"})
    """
    decision = interrupt(
        {
            "question_id": state.get("question_id"),
            "question": state["question"],
            "draft": state.get("draft"),
            "answerable": state.get("answerable"),
            "verified": state.get("verified"),
            "critique": state.get("critique"),
            "revisions": state.get("revision_count", 0),
            "citations": [
                f"{state['retrieved'][i - 1]['source']} :: {state['retrieved'][i - 1]['section']}"
                for i in state.get("citations", [])
                if 1 <= i <= len(state["retrieved"])
            ],
        }
    )

    action = (decision or {}).get("action", "reject")
    if action == "approve":
        return {"status": "approved", "reviewed_by_human": True}
    if action == "edit":
        return {
            "status": "approved",
            "draft": decision.get("answer", state.get("draft")),
            "answerable": True,
            "reviewed_by_human": True,
            "edited_by_human": True,
        }
    return {"status": "rejected", "reviewed_by_human": True}


def route_after_finalise(state: QuestionState) -> str:
    """Auto-approved answers are done. Everything else waits for a person."""
    return "human" if state.get("status") == "needs_review" else "done"
