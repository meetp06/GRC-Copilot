"""Validates evals/golden_set.yaml against the policy corpus.

This is a data test, not a model test. It makes no network calls.

It exists because a typo in expected_section does not raise anything at
evaluation time -- it silently scores context recall as 0 for that question,
forever. You would then go looking for a bug in the retriever. Same failure
class as reporting the wrong step count in week 1: a wrong number sends you
hunting the wrong thing.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest
import yaml

from src.agent.tools import CONTROL_CATALOG

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_SET = REPO_ROOT / "evals" / "golden_set.yaml"
POLICY_DIR = REPO_ROOT / "data" / "policies"

DIFFICULTIES = {"easy", "medium", "hard", "exact", "unanswerable"}
EXPECTED_BAND_COUNTS = {
    "easy": 10,
    "medium": 15,
    "hard": 10,
    "exact": 5,
    "unanswerable": 5,
}

# Imported, not copied. A hardcoded list here would drift from the catalogue the
# agent actually serves, and the test would keep passing while get_control_info()
# returned nothing -- a check that fails open is worse than no check.
KNOWN_CONTROLS = set(CONTROL_CATALOG)


def _sections(path: Path) -> set[str]:
    """Return the '## ' headings of a markdown policy document."""
    return {
        m.group(1).strip()
        for m in re.finditer(
            r"^## (.+)$", path.read_text(encoding="utf-8"), re.MULTILINE
        )
    }


@pytest.fixture(scope="module")
def questions() -> list[dict]:
    data = yaml.safe_load(GOLDEN_SET.read_text(encoding="utf-8"))
    return data["questions"]


@pytest.fixture(scope="module")
def corpus_sections() -> dict[str, set[str]]:
    return {path.name: _sections(path) for path in POLICY_DIR.glob("*.md")}


def test_ids_are_unique(questions: list[dict]) -> None:
    ids = [q["id"] for q in questions]
    duplicates = [qid for qid, n in Counter(ids).items() if n > 1]
    assert not duplicates, f"duplicate ids: {duplicates}"


def test_band_counts_match_the_plan(questions: list[dict]) -> None:
    counts = Counter(q["difficulty"] for q in questions)
    assert (
        set(counts) <= DIFFICULTIES
    ), f"unknown difficulty: {set(counts) - DIFFICULTIES}"
    assert dict(counts) == EXPECTED_BAND_COUNTS


@pytest.mark.parametrize(
    "field", ["id", "question", "difficulty", "category", "expected_chunks"]
)
def test_required_fields_present(questions: list[dict], field: str) -> None:
    missing = [q.get("id", "<no id>") for q in questions if q.get(field) in (None, "")]
    assert not missing, f"{field} missing on: {missing}"


def test_expected_chunks_point_at_real_sections(
    questions: list[dict], corpus_sections: dict[str, set[str]]
) -> None:
    """The check that actually earns this file: a gold chunk that does not exist
    scores 0 and looks like a retriever bug."""
    errors: list[str] = []
    for q in questions:
        for chunk in q["expected_chunks"]:
            source, section = chunk["source"], chunk["section"]
            if source not in corpus_sections:
                errors.append(f"{q['id']}: no such document {source}")
            elif section not in corpus_sections[source]:
                errors.append(f"{q['id']}: {source} has no section {section!r}")
    assert not errors, "\n".join(errors)


def test_answerable_questions_have_ground_truth(questions: list[dict]) -> None:
    for q in questions:
        if q["difficulty"] == "unanswerable":
            continue
        assert q["expected_chunks"], f"{q['id']}: answerable but no expected_chunks"
        assert q.get(
            "ground_truth_answer"
        ), f"{q['id']}: answerable but no ground_truth_answer"


def test_unanswerable_questions_carry_no_answer(questions: list[dict]) -> None:
    """An unanswerable entry with a ground truth would score as a hallucination
    win. Refusal is scored by the evaluator cascade, not from this file."""
    for q in questions:
        if q["difficulty"] != "unanswerable":
            continue
        assert (
            q["expected_chunks"] == []
        ), f"{q['id']}: unanswerable but has expected_chunks"
        assert (
            q["ground_truth_answer"] is None
        ), f"{q['id']}: unanswerable but has an answer"
        assert (
            q["expected_control"] is None
        ), f"{q['id']}: unanswerable but has a control"
        assert q.get(
            "why_unanswerable"
        ), f"{q['id']}: unanswerable without a stated reason"


def test_expected_controls_are_catalogued(questions: list[dict]) -> None:
    unknown = {
        q["id"]: q["expected_control"]
        for q in questions
        if q["expected_control"] is not None
        and q["expected_control"] not in KNOWN_CONTROLS
    }
    assert not unknown, f"controls not in CONTROL_CATALOG: {unknown}"


def test_hard_questions_span_multiple_chunks(questions: list[dict]) -> None:
    """The hard band exists to punish retrieving one chunk and answering
    confidently. A single-chunk 'hard' question does not test that."""
    thin = [
        q["id"]
        for q in questions
        if q["difficulty"] == "hard" and len(q["expected_chunks"]) < 2
    ]
    assert not thin, f"hard questions with fewer than 2 gold chunks: {thin}"


def test_unanswerable_band_includes_lexical_distractors(questions: list[dict]) -> None:
    """At least some refusal tests must have plausible retrieved context.
    Refusing when retrieval returns nothing is the easy case."""
    unanswerable = [q for q in questions if q["difficulty"] == "unanswerable"]
    assert sum(1 for q in unanswerable if q.get("distractor")) >= 2
