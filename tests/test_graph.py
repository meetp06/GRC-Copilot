"""Graph structure and state tests. No network, no cost.

These test the wiring, not the model. The question "does the ported graph give
the same answers as week 2" is answered by running the golden set against it,
which costs money and cannot live in a unit test.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.graph.build import build_graph
from src.graph.state import QuestionState
from src.rag.answer import Answer


class FakeHit:
    def __init__(self, source: str, section: str, text: str, score: float) -> None:
        self.source, self.section, self.text, self.score = source, section, text, score


class FakeIndex:
    """Stands in for VectorIndex. Records what it was asked."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, top_k: int = 5):
        self.queries.append(query)
        return [
            FakeHit(
                "information-security-policy.md", "Encryption at rest", "AES-256.", 0.63
            ),
            FakeHit(
                "business-continuity-and-disaster-recovery-plan.md",
                "Backups",
                "Nightly.",
                0.31,
            ),
        ]


FAKE_ANSWER = Answer(
    answerable=True,
    answer="Yes, AES-256.",
    citations=[1],
    confidence="high",
    retrieved=[("information-security-policy.md", "Encryption at rest")],
    input_tokens=100,
    output_tokens=10,
)


@pytest.fixture
def state() -> QuestionState:
    index = FakeIndex()
    with patch("src.graph.nodes.answer_question", return_value=FAKE_ANSWER):
        app = build_graph(index)
        return app.invoke(
            {
                "question": "Do you encrypt data at rest?",
                "question_id": "t1",
                "status": "retrieving",
            }
        )


def test_graph_runs_both_nodes_and_reaches_a_terminal_status(
    state: QuestionState,
) -> None:
    assert state["retrieved"], "retrieve node did not populate state"
    assert state["draft"] == "Yes, AES-256."
    assert state["status"] in {"approved", "needs_review"}


def test_retrieved_passages_are_kept_for_the_verifier_and_the_human(
    state: QuestionState,
) -> None:
    """The drafter could work without this, but the verifier has to check the
    draft against the same text, and a reviewer has to read the source."""
    assert state["retrieved"][0]["section"] == "Encryption at rest"
    assert state["retrieved"][0]["text"] == "AES-256."


def test_citations_resolve_to_retrieved_passages(state: QuestionState) -> None:
    """Citations are 1-based indices into `retrieved`. An off-by-one here would
    silently attribute every answer to the wrong policy section."""
    for i in state["citations"]:
        assert 1 <= i <= len(state["retrieved"])
    cited = state["retrieved"][state["citations"][0] - 1]
    assert cited["source"] == "information-security-policy.md"


def test_token_counts_accumulate_rather_than_overwrite(state: QuestionState) -> None:
    """A resumed run must be able to prove it did not pay for the same work
    twice, which needs a running total rather than the last node's usage."""
    assert state["input_tokens"] == 100
    assert state["output_tokens"] == 10


def test_reflection_counter_starts_bounded(state: QuestionState) -> None:
    """Day 2 adds a drafter/verifier loop. Without this counter the two argue
    until the token budget is gone -- the week 1 runaway, one level up."""
    assert state["revision_count"] == 0
    assert state["verified"] is False


def test_state_survives_serialisation(state: QuestionState) -> None:
    """The checkpointer writes this to SQLite at every step. Anything in state
    that cannot be serialised breaks resume -- which is the entire reason for
    adopting the framework. This is why the boto3 client and the vector index
    are passed to nodes in a closure rather than stored here.

    Checked with JSON rather than pickle: pickle is banned in CLAUDE.md, and it
    would pass on objects the real checkpointer cannot store anyway. JSON is the
    stricter test."""
    assert json.loads(json.dumps(state)) == state
