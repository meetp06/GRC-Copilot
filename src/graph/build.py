"""Assemble the question graph.

    python -m src.graph.build "Do you encrypt customer data at rest?"

Day 1 topology is deliberately boring -- two nodes in a line:

    START -> retrieve -> draft -> END

It does exactly what week 2 did. The point of shipping it this shape is that the
week 2 eval set can prove the port changed nothing before any new behaviour is
added on top. A framework migration that also adds features is a migration you
cannot debug.

The verifier, the reflection loop and the human interrupt arrive on days 2 and 3.
"""

from __future__ import annotations

import json
import sys

from langgraph.graph import END, START, StateGraph

from src.graph.nodes import make_draft, make_retrieve
from src.graph.state import QuestionState
from src.rag.index import VectorIndex


def build_graph(index: VectorIndex, model_id: str | None = None):
    """Wire the nodes into a compiled graph.

    The index is passed in rather than loaded here so tests can supply their own
    and so a batch run loads it once instead of once per question.
    """
    graph = StateGraph(QuestionState)
    graph.add_node("retrieve", make_retrieve(index))
    graph.add_node("draft", make_draft(index, model_id=model_id))

    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "draft")
    graph.add_edge("draft", END)

    return graph.compile()


def answer(
    question: str, index: VectorIndex, question_id: str = "adhoc"
) -> QuestionState:
    app = build_graph(index)
    return app.invoke(
        {"question": question, "question_id": question_id, "status": "retrieving"}
    )


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
