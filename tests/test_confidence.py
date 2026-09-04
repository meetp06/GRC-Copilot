"""Confidence scoring tests. Pure functions, no network, no cost.

Whether the thresholds are *right* is a question for calibrate.py against the
golden set. What is tested here is that the score behaves the way its docstring
claims: that the signals point the direction they say they do, and that the two
floors override the arithmetic.
"""

from __future__ import annotations

from src.graph.confidence import retrieval_margin, score


def state(**overrides) -> dict:
    base = {
        "answerable": True,
        "verified": True,
        "revision_count": 0,
        "citations": [1],
        "model_confidence": "high",
        "retrieved": [
            {"source": "a.md", "section": "One", "text": "x", "score": 0.60},
            {"source": "b.md", "section": "Two", "text": "y", "score": 0.20},
        ],
    }
    return {**base, **overrides}


def test_everything_good_scores_high() -> None:
    band, reasons = score(state())
    assert band == "high"
    assert reasons["verifier"] == "passed first time"


def test_passing_only_after_revision_is_worth_less() -> None:
    """A draft that was wrong once and survived a single re-check is weaker
    evidence than one that was right the first time."""
    first_try, _ = score(state())
    retried, reasons = score(state(revision_count=1))
    assert retried != first_try or reasons["verifier"].startswith("passed after")
    assert "passed after 1" in reasons["verifier"]


def test_a_narrow_retrieval_margin_lowers_confidence() -> None:
    """Week 2 measured a bare 'SC-28' beating fifth place by 0.026, which is
    noise. A top hit that barely won means the retriever had no real opinion."""
    wide = [
        {"source": "a.md", "section": "One", "text": "x", "score": 0.60},
        {"source": "b.md", "section": "Two", "text": "y", "score": 0.20},
    ]
    narrow = [
        {"source": "a.md", "section": "One", "text": "x", "score": 0.110},
        {"source": "b.md", "section": "Two", "text": "y", "score": 0.084},
    ]
    _, wide_reasons = score(state(retrieved=wide))
    _, narrow_reasons = score(state(retrieved=narrow))
    assert wide_reasons["retrieval"].startswith("decisive")
    assert narrow_reasons["retrieval"].startswith("weak")
    assert wide_reasons["points"] > narrow_reasons["points"]


def test_no_citation_forces_low_regardless_of_everything_else() -> None:
    """An answer nobody can trace is disqualified, not merely downgraded. This
    is a floor that overrides the arithmetic, in a product whose promise is that
    every answer survives an auditor."""
    band, reasons = score(state(citations=[]))
    assert band == "low"
    assert reasons["floor"] == "no citation, forced low"


def test_a_refusal_is_never_high_confidence() -> None:
    """A refusal is routed to a human by definition; a confident refusal would
    auto-approve an answer that says nothing."""
    band, reasons = score(state(answerable=False))
    assert band == "low"
    assert reasons["floor"] == "refusal, forced low"


def test_failing_verification_costs_the_most_points() -> None:
    """The verifier is the strongest signal, so losing it should be the single
    biggest drop available."""
    _, passed = score(state())
    _, failed = score(state(verified=False))
    assert passed["points"] - failed["points"] == 2


def test_margin_needs_at_least_two_passages() -> None:
    """A single retrieved passage has nothing to be compared against, so there
    is no margin to report -- 0.0, not a crash and not a false 'decisive'."""
    single = [{"source": "a.md", "section": "One", "text": "x", "score": 0.9}]
    assert retrieval_margin({"retrieved": single}) == 0.0
    assert retrieval_margin({"retrieved": []}) == 0.0
