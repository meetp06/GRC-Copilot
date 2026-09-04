"""Decide how much to trust an answer, from signals other than the model's opinion.

Confidence drives routing: a high-confidence answer is auto-approved and sent to
a customer, a low one goes to a human. So the number has to mean something, and
"the model said high" is the weakest possible basis for it -- models are
overconfident, and the model's confidence is produced by the same process that
produced the answer, so it cannot be independent evidence about that answer.

Four signals, ordered by how much they are worth:

  verifier passed first time    Strongest. A separate agent read the draft
                                against its cited text and found every claim.
                                A pass after revisions is weaker: the first
                                draft was wrong, and the second survived one
                                check rather than being right from the start.

  retrieval margin              How far the top passage beat the fifth. Week 2
                                measured a bare "SC-28" winning by 0.026, which
                                is noise, against a well-phrased question
                                winning by 0.35. A narrow margin means the
                                retriever had no real opinion, so the drafter
                                was working from a coin flip.

  cited something               An answer citing nothing cannot be checked by
                                anyone, which is disqualifying in a product
                                whose promise is traceability.

  the model's own confidence    Weakest, and included only as a tiebreak.

Whether these weights are any good is not a matter of taste. `calibrate.py`
scores them against the golden set: of the answers marked high, how many were
actually right? An uncalibrated confidence score is decoration.
"""

from __future__ import annotations

from typing import Literal

from src.graph.state import QuestionState

Confidence = Literal["high", "medium", "low"]

# A top hit must beat the last retrieved passage by this much for retrieval to
# count as decisive. Week 2's measured range: 0.026 for a bare control ID that
# retrieval essentially guessed, 0.35 for a question it answered confidently.
DECISIVE_MARGIN = 0.15

# Points needed for each band. Deliberately coarse -- three buckets, not a
# percentage, because a percentage invites false precision from four signals.
HIGH_THRESHOLD = 4
MEDIUM_THRESHOLD = 2


def retrieval_margin(state: QuestionState) -> float:
    """How far the best passage beat the worst one shown to the drafter.

    The absolute top score is not the useful number. A question phrased in the
    policy's own words scores high on everything relevant; a question retrieval
    did not understand scores low on everything, and the top hit wins by
    nothing. The gap is what says whether there was a real decision.
    """
    scores = [chunk["score"] for chunk in state.get("retrieved", [])]
    if len(scores) < 2:
        return 0.0
    return scores[0] - scores[-1]


def score(state: QuestionState) -> tuple[Confidence, dict[str, object]]:
    """Return a confidence band and the reasons for it.

    The breakdown is returned alongside the band because a reviewer looking at a
    flagged answer needs to know *why* it was flagged, and because a score
    nobody can inspect cannot be debugged when calibration says it is wrong.
    """
    points = 0
    reasons: dict[str, object] = {}

    verified = bool(state.get("verified"))
    revisions = int(state.get("revision_count", 0))
    if verified and revisions == 0:
        points += 2
        reasons["verifier"] = "passed first time"
    elif verified:
        points += 1
        reasons["verifier"] = f"passed after {revisions} revision(s)"
    else:
        reasons["verifier"] = "did not pass"

    margin = retrieval_margin(state)
    if margin >= DECISIVE_MARGIN:
        points += 1
        reasons["retrieval"] = f"decisive (margin {margin:.3f})"
    else:
        reasons["retrieval"] = f"weak (margin {margin:.3f})"

    if state.get("citations"):
        points += 1
        reasons["citations"] = len(state["citations"])
    else:
        reasons["citations"] = 0

    if state.get("model_confidence") == "high":
        points += 1
        reasons["model_said"] = "high"
    else:
        reasons["model_said"] = state.get("model_confidence", "unknown")

    # An answer that cites nothing cannot be traced, whatever else it scored.
    # This is a floor, not a signal -- it overrides the arithmetic.
    if not state.get("citations"):
        reasons["floor"] = "no citation, forced low"
        return "low", reasons

    if not state.get("answerable", False):
        reasons["floor"] = "refusal, forced low"
        return "low", reasons

    reasons["points"] = points
    if points >= HIGH_THRESHOLD:
        return "high", reasons
    if points >= MEDIUM_THRESHOLD:
        return "medium", reasons
    return "low", reasons
