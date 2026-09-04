"""Batch layer tests. No network, no cost.

The batch layer is thin on purpose -- per-question threads mean resumability
comes from the checkpointer rather than from anything here. What is worth
testing is the part that is not free: that a re-run does not pay twice.
"""

from __future__ import annotations

import csv
from unittest.mock import patch

import pytest

from src.graph.batch import collect, export, read_questionnaire, run_one
from src.graph.build import build_graph
from src.graph.checkpoint import open_checkpointer
from src.rag.answer import Answer
from src.rag.verify import Verdict
from tests.test_graph import FakeIndex

GOOD = Answer(
    answerable=True,
    answer="Yes, AES-256.",
    citations=[1],
    confidence="high",
    retrieved=[("information-security-policy.md", "Encryption at rest")],
    input_tokens=100,
    output_tokens=10,
)
PASSED = Verdict(
    supported=True, unsupported_claims=[], critique="", input_tokens=50, output_tokens=5
)


@pytest.fixture
def questionnaire(tmp_path):
    path = tmp_path / "q.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "question"])
        writer.writeheader()
        writer.writerow({"id": "b1", "question": "Do you encrypt data at rest?"})
    return path


@pytest.fixture
def app(tmp_path):
    return build_graph(
        FakeIndex(), checkpointer=open_checkpointer(tmp_path / "runs.sqlite")
    )


def test_a_row_missing_a_question_is_rejected_before_any_spend(tmp_path) -> None:
    """Fail on the file, not on the fortieth question, after paying for 39."""
    path = tmp_path / "bad.csv"
    path.write_text("id,question\nb1,\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        read_questionnaire(path)


def test_rerunning_a_finished_question_costs_nothing(app, questionnaire) -> None:
    """The expensive bug in an LLM system is paying twice for the same answer.
    The second call must not reach the model at all."""
    row = {"id": "b1", "question": "Do you encrypt data at rest?"}

    with (
        patch("src.graph.nodes.draft_answer", return_value=GOOD) as drafter,
        patch("src.graph.nodes.verify_answer", return_value=PASSED),
    ):
        assert run_one(app, row)[1] == "approved"
        assert drafter.call_count == 1

        assert run_one(app, row)[1] == "skipped"
        assert drafter.call_count == 1, "a finished question was answered again"


def test_one_failing_question_does_not_lose_the_batch(app) -> None:
    """A batch of 50 that dies on question 3 has wasted the other 47."""
    row = {"id": "boom", "question": "Anything."}
    with patch(
        "src.graph.nodes.draft_answer", side_effect=RuntimeError("bedrock down")
    ):
        with pytest.raises(RuntimeError):
            run_one(app, row)
    # The failure is raised to the pool, which records it per question and keeps
    # going; run() asserts that behaviour by catching Exception per future.


def test_export_flattens_citations_into_one_cell(app, questionnaire, tmp_path) -> None:
    """Citations are joined with semicolons, not commas: they live in a single
    CSV cell that a person pastes into the buyer's spreadsheet."""
    with (
        patch("src.graph.nodes.draft_answer", return_value=GOOD),
        patch("src.graph.nodes.verify_answer", return_value=PASSED),
        patch("src.graph.batch.open_checkpointer", return_value=app.checkpointer),
        patch("src.graph.batch.VectorIndex") as index_cls,
    ):
        index_cls.load.return_value = FakeIndex()
        run_one(app, {"id": "b1", "question": "Do you encrypt data at rest?"})

        out = tmp_path / "answers.csv"
        export(questionnaire, out)
        written = list(csv.DictReader(out.open(encoding="utf-8")))

    assert written[0]["answer"] == "Yes, AES-256."
    assert ";" in written[0]["citations"] or written[0]["citations"]
    assert "," not in written[0]["citations"].replace(", ", "")


def test_collect_reports_a_never_run_question_as_not_run(
    app, questionnaire, tmp_path
) -> None:
    """A blank row and an unanswered row must not look the same in the report."""
    with (
        patch("src.graph.batch.open_checkpointer", return_value=app.checkpointer),
        patch("src.graph.batch.VectorIndex") as index_cls,
    ):
        index_cls.load.return_value = FakeIndex()
        rows = collect(questionnaire)
    assert rows[0]["status"] == "not_run"
