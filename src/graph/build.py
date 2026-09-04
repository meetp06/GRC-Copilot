"""Assemble the question graph.

    python -m src.graph.build "Do you encrypt customer data at rest?"

Day 1 topology is deliberately boring -- two nodes in a line:

    START -> retrieve -> draft -> verify -> finalise -> END
                           ^         |
                           +---------+   at most MAX_REVISIONS times

The verifier is a separate agent, not the drafter checking itself. Week 2
measured why: when retrieval returns a plausible distractor, the drafter's own
`answerable` flag and its answer text both say the answer is fine, because the
drafter is the thing that was fooled. See ADR-0008.

The retry edge is bounded. An unbounded critique-redraft cycle is the week 1
runaway failure one level up, and the counter that stops it lives in state where
no model can reach it.

The human interrupt arrives on day 3.
"""

from __future__ import annotations

import json
import sys

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from src.graph.checkpoint import thread_config
from src.graph.nodes import (
    finalise,
    human_review,
    make_draft,
    make_retrieve,
    make_verify,
    route_after_finalise,
    route_after_verify,
)
from src.graph.state import QuestionState
from src.rag.index import VectorIndex


def build_graph(index: VectorIndex, model_id: str | None = None, checkpointer=None):
    """Wire the nodes into a compiled graph.

    The index is passed in rather than loaded here so tests can supply their own
    and so a batch run loads it once instead of once per question.

    Without a checkpointer the graph still runs but cannot be interrupted --
    LangGraph has nowhere to write the state it would need to resume from. The
    human review node is wired in either way; it simply never gets to pause.
    """
    graph = StateGraph(QuestionState)
    graph.add_node("retrieve", make_retrieve(index))
    graph.add_node("draft", make_draft(model_id=model_id))
    graph.add_node("verify", make_verify(model_id=model_id))
    graph.add_node("finalise", finalise)

    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "draft")
    graph.add_edge("draft", "verify")
    graph.add_conditional_edges(
        "verify",
        route_after_verify,
        # "retry" is the only edge that goes backwards. Everything else moves
        # toward a terminal status, so the graph cannot cycle any other way.
        {"retry": "draft", "accept": "finalise", "give_up": "finalise"},
    )
    graph.add_node("human_review", human_review)
    graph.add_conditional_edges(
        "finalise", route_after_finalise, {"human": "human_review", "done": END}
    )
    graph.add_edge("human_review", END)

    return graph.compile(checkpointer=checkpointer)


def answer(
    question: str, index: VectorIndex, question_id: str = "adhoc"
) -> QuestionState:
    """One question, no checkpointing. Used by the CLI and the eval harness."""
    app = build_graph(index)
    return app.invoke(
        {"question": question, "question_id": question_id, "status": "retrieving"}
    )


def start(question: str, question_id: str, index: VectorIndex, checkpointer) -> dict:
    """Run a question until it finishes or stops for a human.

    Returns the graph's own output. If the question needed review, that output
    carries an `__interrupt__` entry rather than a finished state, and the run
    sits in the checkpoint database until `resume` is called with a decision.
    """
    app = build_graph(index, checkpointer=checkpointer)
    return app.invoke(
        {"question": question, "question_id": question_id, "status": "retrieving"},
        config=thread_config(question_id),
    )


def resume(question_id: str, decision: dict, index: VectorIndex, checkpointer) -> dict:
    """Continue a paused run with a human decision.

    State is read from the checkpoint database, so this works from a different
    process, after a crash, or a week later. Nodes that already ran are not run
    again -- which is the point, because they were paid for.
    """
    app = build_graph(index, checkpointer=checkpointer)
    return app.invoke(Command(resume=decision), config=thread_config(question_id))


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    if len(sys.argv) < 2:
        print('Usage: python -m src.graph.build "your question here"')
        raise SystemExit(1)

    state = answer(" ".join(sys.argv[1:]), VectorIndex.load())
    print(
        json.dumps(
            {
                "status": state["status"],
                "answerable": state["answerable"],
                "verified": state["verified"],
                "revisions": state["revision_count"],
                "confidence": state["confidence"],
                "answer": state["draft"],
                "cited": [
                    f"{state['retrieved'][i - 1]['source']} :: {state['retrieved'][i - 1]['section']}"
                    for i in state["citations"]
                    if 1 <= i <= len(state["retrieved"])
                ],
                "tokens": {
                    "in": state["input_tokens"],
                    "out": state["output_tokens"],
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
