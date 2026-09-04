"""Graph structure and state tests. No network, no cost.

These test the wiring, not the model. The question "does the ported graph give
the same answers as week 2" is answered by running the golden set against it,
which costs money and cannot live in a unit test.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.graph.build import build_graph, resume, start
from src.graph.checkpoint import open_checkpointer, thread_config
from src.graph.review import _pending
from src.graph.state import MAX_REVISIONS, QuestionState
from src.rag.answer import Answer
from src.rag.verify import Verdict


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


GOOD_VERDICT = Verdict(
    supported=True, unsupported_claims=[], critique="", input_tokens=50, output_tokens=5
)
BAD_VERDICT = Verdict(
    supported=False,
    unsupported_claims=["Keys rotate every 90 days."],
    critique="The extracts say annual rotation, not 90 days.",
    input_tokens=50,
    output_tokens=20,
)


def run_graph(answer=FAKE_ANSWER, verdict=GOOD_VERDICT) -> QuestionState:
    with (
        patch("src.graph.nodes.draft_answer", return_value=answer),
        patch("src.graph.nodes.verify_answer", return_value=verdict),
    ):
        app = build_graph(FakeIndex())
        return app.invoke(
            {
                "question": "Do you encrypt data at rest?",
                "question_id": "t1",
                "status": "retrieving",
            }
        )


@pytest.fixture
def state() -> QuestionState:
    return run_graph()


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


def test_token_counts_accumulate_across_nodes(state: QuestionState) -> None:
    """Drafter and verifier both spend tokens. A running total is what lets a
    resumed run prove it did not pay for the same work twice."""
    assert state["input_tokens"] == 150  # 100 draft + 50 verify
    assert state["output_tokens"] == 15  # 10 draft + 5 verify


def test_a_verified_draft_is_approved_without_revisions(state: QuestionState) -> None:
    assert state["verified"] is True
    assert state["revision_count"] == 0
    assert state["status"] == "approved"


def test_reflection_loop_is_bounded() -> None:
    """The verifier rejects every attempt. Without the cap the drafter and
    verifier rewrite and reject each other until the budget is gone -- the week 1
    runaway failure, one level up between two agents."""
    state = run_graph(verdict=BAD_VERDICT)
    assert state["revision_count"] == MAX_REVISIONS
    assert (
        state["status"] == "needs_review"
    ), "a draft that never verified must not auto-approve"


def test_an_unverified_draft_is_never_auto_approved() -> None:
    """The safe default in a compliance product is a human queue, not a send."""
    state = run_graph(verdict=BAD_VERDICT)
    assert state["confidence"] == "low"


def test_a_refusal_skips_verification_entirely() -> None:
    """There is no claim to check in a refusal, and asking a verifier to confirm
    the absence of evidence invites it to argue the answer back into existence.
    It also saves a model call on every refusal."""
    refusal = Answer(
        answerable=False,
        answer="The policy corpus does not cover this.",
        citations=[],
        confidence="low",
        retrieved=[],
        input_tokens=100,
        output_tokens=10,
    )
    state = run_graph(answer=refusal)
    assert state["status"] == "needs_review"
    assert state["input_tokens"] == 100, "verifier should not have been called"


def test_state_survives_serialisation(state: QuestionState) -> None:
    """The checkpointer writes this to SQLite at every step. Anything in state
    that cannot be serialised breaks resume -- which is the entire reason for
    adopting the framework. This is why the boto3 client and the vector index
    are passed to nodes in a closure rather than stored here.

    Checked with JSON rather than pickle: pickle is banned in CLAUDE.md, and it
    would pass on objects the real checkpointer cannot store anyway. JSON is the
    stricter test."""
    assert json.loads(json.dumps(state)) == state


# --- checkpointing and human review -----------------------------------------


def _checkpointed(tmp_path):
    """A graph whose state persists to a real SQLite file."""
    return open_checkpointer(tmp_path / "runs.sqlite")


def _start(checkpointer, answer=FAKE_ANSWER, verdict=GOOD_VERDICT, qid="t1"):
    with (
        patch("src.graph.nodes.draft_answer", return_value=answer),
        patch("src.graph.nodes.verify_answer", return_value=verdict),
    ):
        return start("Do you encrypt data at rest?", qid, FakeIndex(), checkpointer)


REFUSAL = Answer(
    answerable=False,
    answer="The policy corpus does not cover this.",
    citations=[],
    confidence="low",
    retrieved=[],
    input_tokens=100,
    output_tokens=10,
)


def test_a_question_needing_review_pauses_instead_of_finishing(tmp_path) -> None:
    cp = _checkpointed(tmp_path)
    out = _start(cp, answer=REFUSAL)
    assert "__interrupt__" in out, "the graph should have stopped for a human"


def test_paused_state_is_readable_from_a_new_graph_instance(tmp_path) -> None:
    """The reviewer runs a separate command, in a separate process, possibly
    days later. Nothing may be held in memory between pausing and resuming."""
    cp = _checkpointed(tmp_path)
    _start(cp, answer=REFUSAL)

    fresh = build_graph(FakeIndex(), checkpointer=cp)
    snapshot = fresh.get_state(thread_config("t1"))
    assert snapshot.next == ("human_review",)
    assert snapshot.values["status"] == "needs_review"


def test_resuming_does_not_repeat_paid_work(tmp_path) -> None:
    """The reason for adopting a framework, asserted. Token counts must be
    identical across the pause: retrieve, draft and verify already ran and were
    already paid for, so resume must start at the interrupt, not the beginning."""
    cp = _checkpointed(tmp_path)
    _start(cp, answer=REFUSAL)

    fresh = build_graph(FakeIndex(), checkpointer=cp)
    before = fresh.get_state(thread_config("t1")).values["input_tokens"]

    out = resume("t1", {"action": "approve"}, FakeIndex(), cp)
    assert out["input_tokens"] == before
    assert out["status"] == "approved"
    assert out["reviewed_by_human"] is True


def test_an_edit_replaces_the_answer_and_is_recorded_as_edited(tmp_path) -> None:
    """'approved' alone cannot tell an auditor whether a person changed the
    wording. That distinction is the product."""
    cp = _checkpointed(tmp_path)
    _start(cp, answer=REFUSAL)
    out = resume("t1", {"action": "edit", "answer": "Corrected."}, FakeIndex(), cp)
    assert out["draft"] == "Corrected."
    assert out["edited_by_human"] is True


def test_rejecting_clears_it_from_the_review_queue(tmp_path) -> None:
    """Regression: _pending() once used one dict for both deduplication and
    results, so a thread whose newest checkpoint was 'rejected' was never marked
    seen and its older needs_review checkpoint resurfaced as pending."""
    cp = _checkpointed(tmp_path)
    _start(cp, answer=REFUSAL)
    assert len(_pending(cp)) == 1

    resume("t1", {"action": "reject"}, FakeIndex(), cp)
    assert _pending(cp) == [], "a decided question must leave the queue"
