"""SDK tests. A stub transport, no server, no model calls."""

from __future__ import annotations

import httpx
import pytest

from src.sdk.client import (
    GRCClient,
    GRCError,
    JobTimeout,
    NotFoundError,
    ReviewStateError,
)


def client_with(handler) -> GRCClient:
    """A client whose HTTP layer is a function, so no server is needed."""
    client = GRCClient("http://test")
    client._http = httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(handler)
    )
    return client


def test_a_404_becomes_a_named_error_not_a_status_code() -> None:
    """A caller should not have to know what 404 means here."""
    c = client_with(lambda r: httpx.Response(404, json={"detail": "no such job"}))
    with pytest.raises(NotFoundError, match="no such job"):
        c.status("nope")


def test_a_409_becomes_reviewstateerror() -> None:
    """409 specifically means the question exists but is not awaiting review.
    Collapsing it into a generic error would lose the distinction that tells a
    caller whether to retry or to stop."""
    c = client_with(
        lambda r: httpx.Response(409, json={"detail": "not awaiting review"})
    )
    with pytest.raises(ReviewStateError):
        c.approve("q1")


def test_an_unreachable_server_is_not_a_stack_trace() -> None:
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    c = client_with(refuse)
    with pytest.raises(GRCError, match="could not reach the API"):
        c.health()


def test_wait_returns_once_the_job_is_terminal() -> None:
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        status = "running" if calls["n"] < 3 else "done"
        return httpx.Response(
            200,
            json={
                "job_id": "j1",
                "status": status,
                "total": 2,
                "completed": calls["n"],
            },
        )

    c = client_with(handler)
    job = c.wait("j1", timeout=10)
    assert job.done and job.status == "done"
    assert calls["n"] == 3


def test_wait_gives_up_rather_than_hanging_forever() -> None:
    """A job whose worker died never reaches a terminal status. Waiting on it
    without a deadline hangs the caller with no explanation."""
    c = client_with(
        lambda r: httpx.Response(
            200, json={"job_id": "j1", "status": "running", "total": 5}
        )
    )
    with pytest.raises(JobTimeout, match="still running"):
        c.wait("j1", timeout=0.1)


def test_unknown_response_fields_do_not_break_the_client() -> None:
    """The API will grow fields. An older client must ignore them rather than
    raising a TypeError on an unexpected keyword."""
    c = client_with(
        lambda r: httpx.Response(
            200,
            json={"job_id": "j1", "status": "done", "some_future_field": 42},
        )
    )
    assert c.status("j1").job_id == "j1"
