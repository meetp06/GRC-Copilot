"""The state one questionnaire question carries through the graph.

A LangGraph StateGraph is a set of functions ("nodes") that each read this
dict and return the keys they changed. LangGraph merges those returns into the
running state and passes it to the next node. Nothing else is shared -- there is
no hidden context object -- so this file is the complete contract between nodes.

That makes the shape worth arguing about. Two rules were applied:

  Only what a later node reads.  `retrieved` exists because the verifier has to
  check the draft against the same text the drafter saw, and the reviewer has to
  show a human the source. Nothing that is merely interesting goes in here.

  Only what has to survive a crash.  This state gets serialised to SQLite at
  every step so a paused run can resume tomorrow. The boto3 client and the
  vector index are rebuilt on resume, so they are passed to nodes separately and
  never stored here. Anything unpicklable in state is a checkpointer failure
  waiting to happen.
"""

from __future__ import annotations

from typing import Literal, TypedDict

# Where a question is in its life. `needs_review` is the one that matters: it is
# the state a run can sit in for a day while a human decides, which is the whole
# reason this project moved off a hand-written loop.
Status = Literal[
    "retrieving", "drafting", "verifying", "needs_review", "approved", "rejected"
]

Confidence = Literal["high", "medium", "low"]


class RetrievedChunk(TypedDict):
    """One passage handed to the drafter.

    A plain dict rather than the Chunk dataclass from src.rag.chunking, because
    every value in state has to survive being written to SQLite and read back.
    """

    source: str
    section: str
    text: str
    score: float


class QuestionState(TypedDict, total=False):
    """One question's journey. `total=False` because nodes fill this in stages."""

    # --- input, set once ---
    question_id: str
    question: str

    # --- retriever ---
    retrieved: list[RetrievedChunk]

    # --- drafter ---
    answerable: bool
    draft: str
    citations: list[int]  # 1-based indices into `retrieved`, as the model gives them
    model_confidence: Confidence

    # --- verifier (week 3 day 2) ---
    critique: str | None
    verified: bool
    # Bounds the drafter/verifier reflection loop. Unbounded, two agents argue
    # until the budget is gone -- the week 1 runaway failure one level up.
    revision_count: int

    # --- routing ---
    confidence: Confidence
    status: Status

    # --- accounting, so a resumed run can prove it did not pay twice ---
    input_tokens: int
    output_tokens: int
