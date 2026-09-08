"""API tests. No model calls -- the graph is stubbed, so these are free."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.api import jobs
from src.api.main import (
    MAX_QUESTIONS,
    MAX_UPLOAD_BYTES,
    _expected_api_key,
    app,
    read_questionnaire_csv,
    require_api_key,
    thread_id,
)


@pytest.fixture(autouse=True)
def _fresh_api_key_cache():
    """The configured key is cached for the life of the process, because reading
    it from Secrets Manager on every request would add latency and cost to all
    of them. That makes it sticky across tests, so clear it around each one."""
    _expected_api_key.cache_clear()
    yield
    _expected_api_key.cache_clear()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "DB_PATH", tmp_path / "jobs.sqlite")
    return TestClient(app)


def csv_bytes(text: str) -> bytes:
    return text.encode("utf-8")


# --- upload validation ------------------------------------------------------


def test_a_bad_file_is_refused_at_upload_not_mid_run() -> None:
    """A malformed file must fail with a 400 at submit time. Failing forty
    questions into a run the client already believes is progressing is worse
    than failing immediately, and it has already been paid for."""
    with pytest.raises(HTTPException) as err:
        read_questionnaire_csv(csv_bytes("id,question\nq1,\n"), "q.csv")
    assert err.value.status_code == 400
    assert "missing" in err.value.detail


def test_duplicate_question_ids_are_refused() -> None:
    """Question ids are checkpoint thread ids. Two rows sharing one id would
    silently overwrite each other's answers."""
    with pytest.raises(HTTPException) as err:
        read_questionnaire_csv(csv_bytes("id,question\nq1,A?\nq1,B?\n"), "q.csv")
    assert err.value.status_code == 400
    assert "unique" in err.value.detail


def test_an_oversized_upload_is_refused_before_parsing() -> None:
    with pytest.raises(HTTPException) as err:
        read_questionnaire_csv(b"x" * (MAX_UPLOAD_BYTES + 1), "big.csv")
    assert err.value.status_code == 413


def test_non_utf8_is_refused_with_a_reason() -> None:
    with pytest.raises(HTTPException) as err:
        read_questionnaire_csv(b"\xff\xfe\x00bad", "q.csv")
    assert err.value.status_code == 400


def test_a_utf8_bom_is_tolerated() -> None:
    """Excel writes a BOM. Refusing it would reject the most common way a
    questionnaire actually arrives."""
    rows = read_questionnaire_csv("﻿id,question\nq1,Do you encrypt?\n".encode(), "q.csv")
    assert rows == [{"id": "q1", "question": "Do you encrypt?"}]


# --- async job contract -----------------------------------------------------


def test_submit_returns_202_immediately_and_does_not_wait(client) -> None:
    """A 200-question run takes minutes; a blocking request gets killed by a
    load balancer. 202 says accepted, not done."""
    with patch("src.api.main.threading.Thread") as thread:
        response = client.post(
            "/questionnaires",
            files={"file": ("q.csv", "id,question\nq1,Do you encrypt?\n", "text/csv")},
        )
    assert response.status_code == 202
    body = response.json()
    assert body["questions"] == 1
    assert body["status_url"].endswith(body["job_id"])
    thread.assert_called_once(), "work must be handed to a background thread"


def test_an_unknown_job_is_404_not_an_empty_result(client) -> None:
    assert client.get("/questionnaires/nope").status_code == 404
    assert client.get("/questionnaires/nope/answers").status_code == 404


def test_progress_is_reported_while_the_job_is_still_running(client, tmp_path) -> None:
    conn = jobs.connect(tmp_path / "jobs.sqlite")
    job_id = jobs.create(conn, "q.csv", [f"q{i}" for i in range(4)])
    jobs.mark(conn, job_id, status="running", completed=1)

    job = jobs.get(conn, job_id)
    assert job.progress == 0.25
    assert job.status == "running"


def test_a_job_with_no_questions_does_not_divide_by_zero(tmp_path) -> None:
    conn = jobs.connect(tmp_path / "jobs.sqlite")
    job_id = jobs.create(conn, "empty.csv", [])
    assert jobs.get(conn, job_id).progress == 0.0


def test_mark_ignores_unknown_columns(tmp_path) -> None:
    """mark() builds SQL from its keyword names, so it must accept only known
    columns -- otherwise a caller's typo becomes a SQL fragment."""
    conn = jobs.connect(tmp_path / "jobs.sqlite")
    job_id = jobs.create(conn, "q.csv", ["q1"])
    jobs.mark(conn, job_id, completed=1, injected="; DROP TABLE job")
    assert jobs.get(conn, job_id).completed == 1


# --- review contract --------------------------------------------------------


def test_approving_a_question_not_awaiting_review_is_409(client) -> None:
    """Not 404: the question may well exist. It is a state conflict, and the
    status code should say which."""
    with patch("src.api.main.build_graph") as build:
        snapshot = build.return_value.get_state.return_value
        snapshot.values = {"question": "Do you encrypt?", "status": "approved"}
        snapshot.next = ()
        response = client.post("/reviews/job1/q1/approve", json={})
    assert response.status_code == 409


def test_approving_an_unknown_question_is_404(client) -> None:
    with patch("src.api.main.build_graph") as build:
        build.return_value.get_state.return_value.values = {}
        response = client.post("/reviews/job1/nope/approve", json={})
    assert response.status_code == 404


# --- tenant isolation -------------------------------------------------------


def test_two_jobs_with_the_same_question_id_do_not_share_a_checkpoint() -> None:
    """The question id comes from a customer's CSV, and "q1" is what everyone
    writes. Using it directly as the checkpoint thread id meant the second
    customer to upload a q1 read and overwrote the first customer's answer.

    Found by a security review after this was pushed, not by a test."""
    assert thread_id("jobA", "q1") != thread_id("jobB", "q1")
    assert thread_id("jobA", "q1").startswith("jobA")


def test_a_review_decision_names_the_job_not_just_the_question(client) -> None:
    """Approving "q1" with no job would approve whichever tenant happened to own
    that checkpoint. The old route must be gone, not merely superseded."""
    assert client.post("/reviews/q1/approve", json={}).status_code == 404


# --- authentication and limits ----------------------------------------------


def test_no_key_configured_means_open_for_local_use(monkeypatch) -> None:
    """The test suite and local development must work without a key. The startup
    mode is explicit rather than accidental."""
    monkeypatch.delenv("GRC_API_KEY", raising=False)
    _expected_api_key.cache_clear()
    require_api_key(None)  # must not raise


def test_a_configured_key_is_required(monkeypatch) -> None:
    monkeypatch.setenv("GRC_API_KEY", "secret")
    _expected_api_key.cache_clear()
    with pytest.raises(HTTPException) as err:
        require_api_key(None)
    assert err.value.status_code == 401
    with pytest.raises(HTTPException):
        require_api_key("wrong")
    require_api_key("secret")  # must not raise


def test_every_data_route_requires_the_key_and_health_does_not(
    client, monkeypatch
) -> None:
    """Tested by calling the API rather than by inspecting its route table.

    An earlier version of this asserted over app.routes, which does not list
    routes added by include_router in this FastAPI version -- so it passed while
    testing nothing. Behaviour is the thing that matters anyway: a load balancer
    must be able to call /health without a credential, and nothing else may be
    reachable without one.
    """
    monkeypatch.setenv("GRC_API_KEY", "secret")
    _expected_api_key.cache_clear()

    assert client.get("/health").status_code != 401, "health must not need a key"

    for method, path in [
        ("get", "/questionnaires"),
        ("get", "/reviews"),
        ("get", "/gaps"),
        ("get", "/controls/AC-02"),
    ]:
        assert getattr(client, method)(path).status_code == 401, path

    # ...and the same call succeeds once the key is supplied.
    assert (
        client.get("/questionnaires", headers={"X-API-Key": "secret"}).status_code
        == 200
    )


def test_a_huge_questionnaire_is_refused_on_row_count() -> None:
    """2MB of CSV is tens of thousands of questions, each of which costs a
    Bedrock call. A byte cap bounds the upload but not the spend."""
    body = "id,question\n" + "".join(
        f"q{i},Do you encrypt?\n" for i in range(MAX_QUESTIONS + 1)
    )
    with pytest.raises(HTTPException) as err:
        read_questionnaire_csv(body.encode(), "big.csv")
    assert err.value.status_code == 413


# --- telemetry --------------------------------------------------------------


def test_telemetry_records_outcomes_not_content(tmp_path) -> None:
    """This table is read in a support session. CLAUDE.md's rule about never
    logging documents applies to durable state, so no column may hold the
    question, the prompt, or the answer."""
    from src.api import telemetry

    conn = telemetry.connect(tmp_path / "t.sqlite")
    columns = {r[1] for r in conn.execute("PRAGMA table_info(run)").fetchall()}
    forbidden = {"question", "answer", "draft", "prompt", "text", "retrieved"}
    assert not (
        columns & forbidden
    ), f"telemetry must not store content: {columns & forbidden}"


def test_telemetry_never_raises_into_the_caller(tmp_path) -> None:
    """The answer has already been produced and paid for by the time this runs.
    Telemetry that can break a run is worse than no telemetry."""
    from src.api import telemetry

    conn = telemetry.connect(tmp_path / "t.sqlite")
    conn.execute("DROP TABLE run")
    conn.commit()
    telemetry.record(conn, {"question_id": "q1"}, 100)  # must not raise


def test_summary_reports_p95_not_just_an_average(tmp_path) -> None:
    """An average latency hides the tail, and the tail is what a user waiting on
    a 200-question run actually experiences."""
    from src.api import telemetry

    conn = telemetry.connect(tmp_path / "t.sqlite")
    for i, ms in enumerate([100] * 19 + [9000]):
        telemetry.record(conn, {"question_id": f"q{i}", "answerable": True}, ms)

    s = telemetry.summary(conn)
    assert s["runs"] == 20
    assert s["median_ms"] == 100
    assert s["p95_ms"] == 9000, "p95 must surface the outlier the mean would bury"


def test_cost_is_computed_from_tokens_not_guessed(tmp_path) -> None:
    from src.api import telemetry

    conn = telemetry.connect(tmp_path / "t.sqlite")
    telemetry.record(
        conn,
        {
            "question_id": "q1",
            "answerable": True,
            "input_tokens": 1_000_000,
            "output_tokens": 0,
        },
        100,
    )
    assert abs(telemetry.summary(conn)["usd_total"] - 0.06) < 1e-9


def test_the_worker_writes_namespaced_threads(tmp_path, monkeypatch) -> None:
    """The regression that reached production: run_job called thread_config with
    the bare question id, so two tenants' q1 shared a checkpoint. Three separate
    string-replace patches to this file silently missed this call site, and the
    bug was only visible by reading the deployed DynamoDB table -- the partition
    keys were "e3" and "f1" rather than "{job}:{question}".

    Asserted on the source rather than by running the worker, because running it
    needs Bedrock. A grep-shaped test is a poor test in general and the right one
    here: the failure mode was an edit that did not apply."""
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src/api/main.py").read_text()
    bare = re.findall(r"thread_config\((?!thread\b|thread_id\()([^)]*)\)", source)
    assert not bare, f"thread_config called without namespacing: {bare}"
