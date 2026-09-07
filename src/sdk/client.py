"""Python client for the GRC Copilot API.

    from src.sdk.client import GRCClient

    with GRCClient("http://localhost:8000") as client:
        job = client.submit("questionnaire.csv")
        job = client.wait(job.job_id)          # polls until done
        for answer in client.answers(job.job_id):
            print(answer.question, answer.answer, answer.citations)

The API already exists, so the reason to wrap it is not access -- it is that
three things are tedious and easy to get wrong, and every caller would otherwise
reimplement them:

    submit ─▶ poll until done ─▶ read answers
               ↑
        this is the bit people get wrong

  polling      `wait()` backs off and gives up rather than hammering the server
               in a tight loop or hanging forever on a job that died.
  types        Answers come back as objects with named fields, so a typo in
               `answer.confidence` fails at the call site rather than returning
               None from a dict three functions later.
  errors       An HTTP 409 becomes a ReviewStateError. A caller should not have
               to know that 409 means "not awaiting review".

httpx is used rather than requests because it is already in the dependency tree
(FastAPI's test client uses it) and this adds nothing new.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"

# Polling starts fast, because a short questionnaire finishes in seconds, then
# backs off so a long one does not cost hundreds of requests.
POLL_START_SECONDS = 1.0
POLL_MAX_SECONDS = 10.0
POLL_BACKOFF = 1.5


class GRCError(Exception):
    """Any error from the API."""


class NotFoundError(GRCError):
    """The job, question or control does not exist."""


class ReviewStateError(GRCError):
    """The question is not awaiting review, so it cannot be approved or rejected."""


class JobTimeout(GRCError):
    """The job did not finish inside the timeout. It may still be running."""


@dataclass(frozen=True)
class Job:
    job_id: str
    filename: str = ""
    status: str = "accepted"
    total: int = 0
    completed: int = 0
    needs_review: int = 0
    failed: int = 0
    progress: float = 0.0
    error: str | None = None
    created_at: str = ""
    finished_at: str | None = None

    @property
    def done(self) -> bool:
        return self.status in {"done", "failed"}


@dataclass(frozen=True)
class Answer:
    question_id: str
    question: str
    status: str
    answerable: bool | None = None
    answer: str | None = None
    confidence: str | None = None
    citations: list[str] = field(default_factory=list)
    controls: list[str] = field(default_factory=list)
    soc2: list[str] = field(default_factory=list)
    reviewed_by_human: bool = False

    @property
    def needs_review(self) -> bool:
        return self.status == "needs_review"


def _job(payload: dict) -> Job:
    return Job(**{k: v for k, v in payload.items() if k in Job.__dataclass_fields__})


def _answer(payload: dict) -> Answer:
    return Answer(
        **{k: v for k, v in payload.items() if k in Answer.__dataclass_fields__}
    )


class GRCClient:
    """A thin, typed client. One HTTP connection, reused."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 30.0) -> None:
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    def __enter__(self) -> GRCClient:
        return self

    def __exit__(
        self, exc_type: type | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs) -> dict | list:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise GRCError(f"could not reach the API: {exc}") from exc

        if response.status_code == 404:
            raise NotFoundError(_detail(response))
        if response.status_code == 409:
            raise ReviewStateError(_detail(response))
        if response.status_code >= 400:
            raise GRCError(f"{response.status_code}: {_detail(response)}")
        return response.json()

    # --- questionnaires ---------------------------------------------------

    def health(self) -> dict:
        return self._request("GET", "/health")

    def submit(self, path: str | Path) -> Job:
        """Upload a questionnaire CSV. Returns immediately; the run is async."""
        path = Path(path)
        with path.open("rb") as handle:
            payload = self._request(
                "POST",
                "/questionnaires",
                files={"file": (path.name, handle, "text/csv")},
            )
        return Job(
            job_id=payload["job_id"], filename=path.name, total=payload["questions"]
        )

    def status(self, job_id: str) -> Job:
        return _job(self._request("GET", f"/questionnaires/{job_id}"))

    def wait(self, job_id: str, timeout: float = 900.0, on_progress=None) -> Job:
        """Poll until the job finishes, with backoff.

        Raises JobTimeout rather than looping forever: a job whose worker died
        never reaches a terminal status, and a client that waits on it hangs
        with no explanation.
        """
        deadline = time.monotonic() + timeout
        delay = POLL_START_SECONDS
        while True:
            job = self.status(job_id)
            if on_progress:
                on_progress(job)
            if job.done:
                return job
            if time.monotonic() >= deadline:
                raise JobTimeout(
                    f"{job_id} still {job.status} after {timeout:.0f}s "
                    f"({job.completed}/{job.total} done)"
                )
            time.sleep(
                min(delay, POLL_MAX_SECONDS, max(0.0, deadline - time.monotonic()))
            )
            delay *= POLL_BACKOFF

    def answers(self, job_id: str) -> list[Answer]:
        return [
            _answer(a)
            for a in self._request("GET", f"/questionnaires/{job_id}/answers")
        ]

    def jobs(self, limit: int = 20) -> list[Job]:
        return [
            _job(j)
            for j in self._request("GET", "/questionnaires", params={"limit": limit})
        ]

    # --- review -----------------------------------------------------------

    def reviews(self) -> list[Answer]:
        return [_answer(a) for a in self._request("GET", "/reviews")]

    def approve(self, question_id: str, answer: str | None = None) -> Answer:
        """Approve a pending answer, optionally replacing its text."""
        return _answer(
            self._request(
                "POST", f"/reviews/{question_id}/approve", json={"answer": answer}
            )
        )

    def reject(self, question_id: str, reason: str | None = None) -> Answer:
        return _answer(
            self._request(
                "POST", f"/reviews/{question_id}/reject", json={"reason": reason}
            )
        )

    # --- ontology ---------------------------------------------------------

    def control(self, label: str) -> dict:
        return self._request("GET", f"/controls/{label}")

    def gaps(self, confirmed_only: bool = False) -> dict:
        return self._request("GET", "/gaps", params={"confirmed_only": confirmed_only})


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", response.text))
    except Exception:
        return response.text
