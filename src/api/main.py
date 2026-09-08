"""HTTP API. Someone who has never seen the code can use this.

    uvicorn src.api.main:app --reload        # docs at /docs

    POST /questionnaires                 upload a CSV, get a job_id back
    GET  /questionnaires                 recent jobs
    GET  /questionnaires/{id}            status and progress
    GET  /questionnaires/{id}/answers    answers, citations, controls
    GET  /reviews                        what is waiting for a human
    POST /reviews/{job}/{qid}/approve    approve, optionally with an edit
    POST /reviews/{job}/{qid}/reject     reject
    GET  /controls/{label}               one control and what satisfies it
    GET  /gaps                           controls with no policy behind them
    GET  /health

The interesting design problem is the long run. Answering 50 questions takes
about a minute and 200 would take four, which is longer than a load balancer
will hold a connection open. So:

    POST /questionnaires -> 202 Accepted + job_id     (returns immediately)
                         ↘ background thread runs the batch
    GET  /questionnaires/{id} -> progress             (client polls)

202 rather than 200 because the work has been *accepted*, not done, and the
status code should not claim otherwise.

Security decisions that are not defaults:

  Uploads are capped and parsed as text, never executed or stored as a path the
  client controls -- CLAUDE.md says to treat questionnaire input as hostile, and
  that is the same input that produced the CSV injection in MISTAKES entry 23.

  No answer text appears in a log line. The prompts and answers contain customer
  policy content by design.
"""

from __future__ import annotations

import csv
import io
import threading
from typing import Annotated

import functools
import hmac
import os
from pathlib import Path

from fastapi import (
    APIRouter,
    Body,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Security,
    UploadFile,
)
from fastapi.responses import HTMLResponse, Response
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from src.api import telemetry
from src.api.jobs import Job
from src.api.store import index_dir, job_store, on_lambda, open_checkpointer
from src.graph.batch import csv_safe
from src.graph.build import build_graph, resume
from src.graph.checkpoint import thread_config
from src.graph.controls import controls_for
from src.ontology.store import connect as ontology_connect
from src.rag.index import VectorIndex

# --------------------------------------------------------------------------
# authentication


@functools.lru_cache(maxsize=1)
def _expected_api_key() -> str | None:
    """The configured key, from Secrets Manager on Lambda and the environment
    locally.

    Cached: a Secrets Manager call per request would add latency and cost to
    every single request, and the value does not change within a container's
    life. Rotating the key means a new deployment, which is stated in the
    threat model rather than pretended otherwise.
    """
    arn = os.environ.get("API_KEY_SECRET_ARN")
    if not arn:
        return os.environ.get("GRC_API_KEY")

    import boto3

    return boto3.client("secretsmanager").get_secret_value(SecretId=arn)["SecretString"]


# Declared as a security scheme rather than a plain Header, so the key appears
# in the OpenAPI document. That is what puts the Authorize button in /docs --
# without it the interactive docs render every endpoint and every call from them
# returns 401, which reads as a broken API rather than a protected one.
#
# auto_error=False so the 401 is raised below, with our message, and so an
# unset GRC_API_KEY still means open -- the local development mode described
# in the docstring.
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(
    x_api_key: Annotated[str | None, Security(api_key_scheme)] = None,
) -> None:
    """Reject a request without the shared key.

    A shared key is the weakest thing that is not nothing. It gives no identity,
    no per-tenant authorisation, and no revocation short of rotating it for
    everyone -- so it does not make this multi-tenant, and the threat model says
    so (T6). What it does is stop the API being usable by anyone who can reach
    the port, which was the state a security review found it in.

    GRC_API_KEY unset means unauthenticated, and that is deliberate: local
    development and the test suite would otherwise need a key to do anything.
    The startup banner says which mode it is in, because an API that is silently
    open is the failure being fixed here.

    hmac.compare_digest rather than ==, so the comparison does not leak the key
    one character at a time through response timing.
    """
    expected = _expected_api_key()
    if not expected:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(401, "missing or invalid X-API-Key")


app = FastAPI(
    title="GRC Copilot",
    version="0.6.0",
    description="Answers security questionnaires from your own policy corpus, with citations.",
)

# Everything that touches data hangs off this router, so a new endpoint is
# protected by adding it here rather than by remembering a decorator.
#
# A router rather than an app-level dependency: FastAPI applies app-level
# dependencies to every route including /health, and `dependencies=[]` on a
# route does not opt out of them. A health check that needs a credential cannot
# be called by a load balancer, which makes it useless as a health check.
api = APIRouter(dependencies=[Depends(require_api_key)])

# A questionnaire is a few hundred rows of text. Anything larger is a mistake or
# an attack, and refusing it before reading is cheaper than either.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024

# A row count cap as well as a byte cap. 2MB of CSV is tens of thousands of
# questions, each of which costs a Bedrock call -- so the byte limit alone
# bounds the upload but not the spend.
MAX_QUESTIONS = 500

INDEX_NAME = "real"

UI_PATH = Path(__file__).parent / "ui.html"

# Even though the page never parses API output as HTML, a second line of defence
# is cheap here. connect-src 'self' is the one that matters: if markup ever did
# execute, it still could not post the API key to another host. 'unsafe-inline'
# is required because the page is one file with no build step -- the trade is
# stated rather than hidden.
UI_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "img-src 'self' data:; "
    "form-action 'none'; "
    "frame-ancestors 'none'"
)


def thread_id(job_id: str, question_id: str) -> str:
    """Checkpoint thread id for one question of one job.

    Namespaced by job, and this is a security boundary rather than tidiness.
    The question id comes from a customer's CSV, and "q1" is the most likely
    id anyone writes. Using it directly as the thread id means two customers
    who both upload a q1 share a checkpoint: the second run reads and
    overwrites the first's answers, across tenants.

    Found by a security review after the API was pushed, not by a test.
    """
    return f"{job_id}:{question_id}"


_index: VectorIndex | None = None
_lock = threading.Lock()


def index() -> VectorIndex:
    """Load the vector index once and share it.

    Loading per request would re-read the index from disk on every call; loading
    at import time would make the module impossible to import without one.
    """
    global _index
    with _lock:
        if _index is None:
            # index_dir() downloads from S3 on Lambda and is a local path
            # otherwise, so this line is the same in both.
            _index = VectorIndex.load(INDEX_NAME, index_dir())
    return _index


# --------------------------------------------------------------------------
# models


class JobAccepted(BaseModel):
    job_id: str
    questions: int
    status_url: str


class JobStatus(BaseModel):
    job_id: str
    filename: str
    status: str
    total: int
    completed: int
    needs_review: int
    failed: int
    progress: float
    error: str | None = None
    created_at: str
    finished_at: str | None = None


class Answer(BaseModel):
    question_id: str
    job_id: str | None = None
    question: str
    status: str
    answerable: bool | None = None
    answer: str | None = None
    confidence: str | None = None
    citations: list[str] = Field(default_factory=list)
    controls: list[str] = Field(default_factory=list)
    soc2: list[str] = Field(default_factory=list)
    reviewed_by_human: bool = False


class ReviewDecision(BaseModel):
    answer: str | None = Field(
        default=None, description="Replacement text. Only used when approving an edit."
    )
    reason: str | None = Field(default=None, description="Why this was rejected.")


# --------------------------------------------------------------------------
# helpers


def read_questionnaire_csv(raw: bytes, filename: str) -> list[dict]:
    """Parse an uploaded CSV into rows, or refuse it with a reason.

    Validation happens here rather than in the worker so a bad file fails at
    upload with a 400, instead of failing forty questions into a run the client
    already believes is in progress.
    """
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file is larger than {MAX_UPLOAD_BYTES // 1024}KB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "file must be UTF-8 text") from None

    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise HTTPException(400, "no rows found")

    missing = [
        i
        for i, r in enumerate(rows, start=2)
        if not r.get("id") or not r.get("question")
    ]
    if missing:
        raise HTTPException(
            400, f"rows missing an id or question column: {missing[:5]}"
        )

    if len(rows) > MAX_QUESTIONS:
        raise HTTPException(
            413, f"{len(rows)} questions; the limit is {MAX_QUESTIONS} per upload"
        )

    ids = [r["id"].strip() for r in rows]
    if len(set(ids)) != len(ids):
        raise HTTPException(400, "question ids must be unique")

    return [{"id": r["id"].strip(), "question": r["question"].strip()} for r in rows]


def run_job(job_id: str, rows: list[dict]) -> None:
    """Answer every question in a job. Runs in a background thread.

    One question failing does not fail the job: a batch of 200 that dies on
    question 3 has wasted the other 197. Failures are counted and reported.
    """
    store = job_store()
    checkpointer = open_checkpointer()
    graph = build_graph(index(), checkpointer=checkpointer)
    store.mark(job_id, status="running")

    metrics = telemetry.connect()
    completed = needs_review = failed = 0
    for row in rows:
        try:
            with telemetry.timed() as elapsed:
                out = graph.invoke(
                    {
                        "question": row["question"],
                        "question_id": row["id"],
                        "status": "retrieving",
                    },
                    config=thread_config(thread_id(job_id, row["id"])),
                )
            if "__interrupt__" in out:
                needs_review += 1
            # Read the settled state rather than the invoke() return: an
            # interrupted run returns the interrupt payload, not the counters.
            state = (
                graph.get_state(thread_config(thread_id(job_id, row["id"]))).values
                or {}
            )
            telemetry.record(
                metrics,
                {**state, "question_id": row["id"]},
                elapsed["ms"],
                job_id=job_id,
            )
        except Exception:
            # Deliberately not logging the exception text: it can contain the
            # prompt, which contains customer policy content.
            failed += 1
        completed += 1
        # The DynamoDB store adds to its counters and the SQLite one assigns,
        # so send the delta or the total depending on which is behind this.
        if getattr(store, "counters_are_additive", False):
            store.mark(job_id, completed=1)
        else:
            store.mark(
                job_id,
                completed=completed,
                needs_review=needs_review,
                failed=failed,
            )

    if getattr(store, "counters_are_additive", False):
        store.mark(job_id, needs_review=needs_review, failed=failed)
    store.finish(job_id, "done" if failed < len(rows) else "failed")


def answer_for(
    graph, thread: str, question_id: str, question: str, job_id: str | None = None
) -> Answer:
    snapshot = graph.get_state(thread_config(thread))
    values = snapshot.values or {}
    if not values:
        return Answer(
            question_id=question_id, job_id=job_id, question=question, status="not_run"
        )

    retrieved = values.get("retrieved", [])
    mapped = controls_for(values)
    return Answer(
        question_id=question_id,
        job_id=job_id,
        question=question,
        status="needs_review" if snapshot.next else values.get("status", "unknown"),
        answerable=values.get("answerable"),
        answer=values.get("draft"),
        confidence=values.get("confidence"),
        citations=[
            f"{retrieved[i - 1]['source']} :: {retrieved[i - 1]['section']}"
            for i in values.get("citations", [])
            if 1 <= i <= len(retrieved)
        ],
        controls=[c["label"] for c in mapped["controls"]],
        soc2=mapped["soc2"],
        reviewed_by_human=bool(values.get("reviewed_by_human")),
    )


# --------------------------------------------------------------------------
# routes


@app.get("/")
def root() -> dict:
    """What this is and how to call it.

    Unauthenticated, like /health, and it lists endpoints without exposing any
    data. Someone opening the URL in a browser previously got
    {"detail":"Not Found"}, which is correct and useless -- there is no route at
    "/", and nothing said so.
    """
    return {
        "service": "GRC Copilot",
        "description": (
            "Answers security questionnaires from a company's own policy corpus, "
            "with a citation for every answer."
        ),
        "docs": "/docs",
        "source": "https://github.com/meetp06/GRC-Copilot",
        "auth": "Send X-API-Key on everything except / and /health.",
        "endpoints": {
            "GET  /ui": "the page a person uses -- start here",
            "GET  /health": "index status, no key required",
            "POST /questionnaires": "upload a CSV of id,question -- returns a job id",
            "GET  /questionnaires/{job}": "progress",
            "GET  /questionnaires/{job}/answers": "answers, citations, NIST controls, SOC 2",
            "GET  /questionnaires/{job}/export.csv": "the completed questionnaire, for a spreadsheet",
            "GET  /reviews": "answers awaiting a human",
            "POST /reviews/{job}/{question}/approve": "approve, optionally with an edit",
            "POST /reviews/{job}/{question}/reject": "reject",
            "GET  /controls/{label}": "one NIST control and what satisfies it",
            "GET  /gaps": "controls with no policy behind them",
        },
    }


@app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
def ui() -> HTMLResponse:
    """The page a person uses, as opposed to /docs which is for a developer.

    Unauthenticated because it is markup and nothing else -- no answer, no
    question, no key. The key is typed into the page by whoever opens it, and
    every call the page makes carries it like any other client.

    Served from the API rather than from S3 so that it shares an origin with the
    API: no CORS to configure, and therefore no CORS to configure wrongly.
    """
    return HTMLResponse(
        UI_PATH.read_text(encoding="utf-8"),
        headers={"Content-Security-Policy": UI_CSP},
    )


@app.get("/health")
def health() -> dict:
    """Reports whether the index is actually loadable, not just that the process
    is up. A health check that only proves the web server started will report
    healthy while every answer fails."""
    try:
        chunks = len(index().chunks)
        return {"status": "ok", "index": INDEX_NAME, "chunks": chunks}
    except FileNotFoundError:
        raise HTTPException(
            503, f"no index named '{INDEX_NAME}'; run src.rag.index build"
        ) from None


@api.post("/questionnaires", status_code=202, response_model=JobAccepted)
def submit(
    file: Annotated[UploadFile, File(description="CSV with id,question columns")],
) -> JobAccepted:
    rows = read_questionnaire_csv(file.file.read(), file.filename or "upload.csv")
    store = job_store()
    job_id = store.create(file.filename or "upload.csv", [r["id"] for r in rows])

    if on_lambda():
        # A daemon thread does not survive the response on Lambda: the runtime
        # freezes the container the moment the handler returns, and the thread
        # resumes only if another request happens to land on it. So the work runs
        # inline, which is why the API caps a questionnaire at 500 questions --
        # comfortably inside the 300-second function timeout.
        run_job(job_id, rows)
    else:
        threading.Thread(target=run_job, args=(job_id, rows), daemon=True).start()
    return JobAccepted(
        job_id=job_id, questions=len(rows), status_url=f"/questionnaires/{job_id}"
    )


@api.get("/questionnaires", response_model=list[JobStatus])
def list_jobs(limit: int = 20) -> list[JobStatus]:
    return [
        JobStatus(job_id=j.id, progress=round(j.progress, 3), **_job_fields(j))
        for j in job_store().recent(limit)
    ]


def _job_fields(job: Job) -> dict:
    return {
        "filename": job.filename,
        "status": job.status,
        "total": job.total,
        "completed": job.completed,
        "needs_review": job.needs_review,
        "failed": job.failed,
        "error": job.error,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }


@api.get("/questionnaires/{job_id}", response_model=JobStatus)
def job_status(job_id: str) -> JobStatus:
    job = job_store().get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    return JobStatus(job_id=job.id, progress=round(job.progress, 3), **_job_fields(job))


@api.get("/questionnaires/{job_id}/answers", response_model=list[Answer])
def job_answers(job_id: str) -> list[Answer]:
    store = job_store()
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")

    graph = build_graph(index(), checkpointer=open_checkpointer())
    return [
        answer_for(
            graph,
            thread_id(job_id, qid),
            qid,
            _question_text(graph, thread_id(job_id, qid)),
            job_id,
        )
        for qid in store.question_ids(job_id)
    ]


EXPORT_COLUMNS = [
    "id",
    "question",
    "answer",
    "confidence",
    "citations",
    "controls",
    "soc2",
    "status",
    "reviewed_by_human",
]


@api.get(
    "/questionnaires/{job_id}/export.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def export_answers(job_id: str) -> Response:
    """The completed questionnaire as a CSV, in the shape a buyer opens in Excel.

    This is the artifact the customer actually wants back; /answers returns the
    same data as JSON for a program to consume.

    csv_safe is imported from the batch exporter rather than reimplemented. Two
    copies of a formula-injection escape is two places for it to rot, and this
    one is newer -- see MISTAKES, where the batch export shipped without it.
    """
    rows = job_answers(job_id)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "id": csv_safe(row.question_id),
                "question": csv_safe(row.question),
                "answer": csv_safe(row.answer),
                "confidence": csv_safe(row.confidence),
                # Semicolons, not commas: each of these is one cell.
                "citations": csv_safe("; ".join(row.citations)),
                "controls": csv_safe("; ".join(row.controls)),
                "soc2": csv_safe("; ".join(row.soc2)),
                "status": csv_safe(row.status),
                "reviewed_by_human": row.reviewed_by_human,
            }
        )

    # job_id reaches a response header, so it is restricted to characters that
    # cannot terminate one. job_answers has already 404ed on an unknown id, so
    # this is defence in depth rather than the only check.
    safe_id = "".join(c for c in job_id if c.isalnum() or c in "-_")[:64]
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_id}-answers.csv"'
        },
    )


def _question_text(graph, thread: str) -> str:
    return (graph.get_state(thread_config(thread)).values or {}).get("question", "")


@api.get("/reviews", response_model=list[Answer])
def reviews() -> list[Answer]:
    """Everything parked at the human-review interrupt, across all jobs."""
    store = job_store()
    graph = build_graph(index(), checkpointer=open_checkpointer())

    out: list[Answer] = []
    for job in store.recent(limit=100):
        for qid in store.question_ids(job.id):
            # Namespaced, or two tenants' q1 collide -- MISTAKES entry 35.
            thread = thread_id(job.id, qid)
            snapshot = graph.get_state(thread_config(thread))
            if snapshot.next == ("human_review",):
                out.append(
                    answer_for(
                        graph,
                        thread,
                        qid,
                        (snapshot.values or {}).get("question", ""),
                        job.id,
                    )
                )
    return out


@api.post("/reviews/{job_id}/{question_id}/approve", response_model=Answer)
def approve(
    job_id: str,
    question_id: str,
    decision: Annotated[ReviewDecision, Body()] = ReviewDecision(),
) -> Answer:
    action = (
        {"action": "edit", "answer": decision.answer}
        if decision.answer
        else {"action": "approve"}
    )
    return _decide(job_id, question_id, action)


@api.post("/reviews/{job_id}/{question_id}/reject", response_model=Answer)
def reject(
    job_id: str,
    question_id: str,
    decision: Annotated[ReviewDecision, Body()] = ReviewDecision(),
) -> Answer:
    return _decide(job_id, question_id, {"action": "reject", "reason": decision.reason})


def _decide(job_id: str, question_id: str, action: dict) -> Answer:
    """Approve or reject one question of one job.

    The route carries the job id as well as the question id, because a question
    id alone does not identify a run. Two customers can both upload a q1, and
    approving "q1" would otherwise approve whichever of them happened to own
    that checkpoint.
    """
    thread = thread_id(job_id, question_id)
    checkpointer = open_checkpointer()
    graph = build_graph(index(), checkpointer=checkpointer)
    snapshot = graph.get_state(thread_config(thread))
    if not snapshot.values:
        raise HTTPException(404, "no such question")
    if snapshot.next != ("human_review",):
        raise HTTPException(409, "this question is not awaiting review")

    resume(thread, action, index(), checkpointer)
    return answer_for(
        graph, thread, question_id, snapshot.values.get("question", ""), job_id
    )


@api.get("/controls/{label}")
def control(label: str) -> dict:
    """One control, and which policy sections are claimed to satisfy it."""
    conn = ontology_connect()
    row = conn.execute(
        "SELECT id, label, title, statement FROM control WHERE lower(label) = lower(?)",
        (label,),
    ).fetchone()
    if not row:
        raise HTTPException(404, f"no control {label}")

    sections = conn.execute(
        """
        SELECT p.source, p.section, s.confidence, s.confirmed_by
        FROM satisfies s JOIN policy_section p ON p.id = s.section_id
        WHERE s.control_id = ? ORDER BY s.confidence DESC
        """,
        (row["id"],),
    ).fetchall()
    criteria = [
        r["criterion"]
        for r in conn.execute(
            "SELECT DISTINCT criterion FROM crosswalk WHERE control_id = ? ORDER BY criterion",
            (row["id"],),
        )
    ]
    return {
        "label": row["label"],
        "title": row["title"],
        "statement": row["statement"],
        "soc2": criteria,
        "satisfied_by": [
            {
                "source": s["source"],
                "section": s["section"],
                "confidence": round(s["confidence"], 3),
                # Surfaced, not hidden. A machine proposed this edge until a
                # named person accepted it.
                "confirmed_by": s["confirmed_by"],
            }
            for s in sections
        ],
    }


@api.get("/gaps")
def gaps(confirmed_only: bool = False) -> dict:
    """Controls with no policy section behind them, by family.

    `confirmed_only=true` is the honest number: an unconfirmed machine proposal
    is not coverage.
    """
    conn = ontology_connect()
    # One of exactly two literals, chosen by a bool. Nothing user-supplied
    # reaches the query text. (nosec B608 on the execute below.)
    clause = "AND s.confirmed_by IS NOT NULL" if confirmed_only else ""
    rows = conn.execute(
        f"""
        SELECT f.title AS family, COUNT(*) AS missing
        FROM control c JOIN control_family f ON f.id = c.family_id
        WHERE c.parent_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM satisfies s WHERE s.control_id = c.id {clause})
        GROUP BY f.title ORDER BY missing DESC
        """  # nosec B608
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) FROM control WHERE parent_id IS NULL"
    ).fetchone()[0]
    missing = sum(r["missing"] for r in rows)
    return {
        "basis": "confirmed" if confirmed_only else "proposed_or_confirmed",
        "controls_total": total,
        "controls_without_policy": missing,
        "by_family": [{"family": r["family"], "missing": r["missing"]} for r in rows],
    }


# Registered last so every route above is defined on the protected router first.
app.include_router(api)
