"""HTTP API. Someone who has never seen the code can use this.

    uvicorn src.api.main:app --reload        # docs at /docs

    POST /questionnaires                 upload a CSV, get a job_id back
    GET  /questionnaires                 recent jobs
    GET  /questionnaires/{id}            status and progress
    GET  /questionnaires/{id}/answers    answers, citations, controls
    GET  /reviews                        what is waiting for a human
    POST /reviews/{qid}/approve          approve, optionally with an edit
    POST /reviews/{qid}/reject           reject
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

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from src.api import jobs
from src.graph.build import build_graph, resume
from src.graph.checkpoint import open_checkpointer, thread_config
from src.graph.controls import controls_for
from src.ontology.store import connect as ontology_connect
from src.rag.index import VectorIndex

app = FastAPI(
    title="GRC Copilot",
    version="0.5.0",
    description="Answers security questionnaires from your own policy corpus, with citations.",
)

# A questionnaire is a few hundred rows of text. Anything larger is a mistake or
# an attack, and refusing it before reading is cheaper than either.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024

INDEX_NAME = "real"

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
            _index = VectorIndex.load(INDEX_NAME)
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

    ids = [r["id"].strip() for r in rows]
    if len(set(ids)) != len(ids):
        raise HTTPException(400, "question ids must be unique")

    return [{"id": r["id"].strip(), "question": r["question"].strip()} for r in rows]


def run_job(job_id: str, rows: list[dict]) -> None:
    """Answer every question in a job. Runs in a background thread.

    One question failing does not fail the job: a batch of 200 that dies on
    question 3 has wasted the other 197. Failures are counted and reported.
    """
    conn = jobs.connect()
    checkpointer = open_checkpointer()
    graph = build_graph(index(), checkpointer=checkpointer)
    jobs.mark(conn, job_id, status="running")

    completed = needs_review = failed = 0
    for row in rows:
        try:
            out = graph.invoke(
                {
                    "question": row["question"],
                    "question_id": row["id"],
                    "status": "retrieving",
                },
                config=thread_config(row["id"]),
            )
            if "__interrupt__" in out:
                needs_review += 1
        except Exception:
            # Deliberately not logging the exception text: it can contain the
            # prompt, which contains customer policy content.
            failed += 1
        completed += 1
        jobs.mark(
            conn,
            job_id,
            completed=completed,
            needs_review=needs_review,
            failed=failed,
        )

    jobs.finish(conn, job_id, "done" if failed < len(rows) else "failed")


def answer_for(graph, question_id: str, question: str) -> Answer:
    snapshot = graph.get_state(thread_config(question_id))
    values = snapshot.values or {}
    if not values:
        return Answer(question_id=question_id, question=question, status="not_run")

    retrieved = values.get("retrieved", [])
    mapped = controls_for(values)
    return Answer(
        question_id=question_id,
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


@app.post("/questionnaires", status_code=202, response_model=JobAccepted)
def submit(
    file: Annotated[UploadFile, File(description="CSV with id,question columns")],
) -> JobAccepted:
    rows = read_questionnaire_csv(file.file.read(), file.filename or "upload.csv")
    conn = jobs.connect()
    job_id = jobs.create(conn, file.filename or "upload.csv", [r["id"] for r in rows])

    threading.Thread(target=run_job, args=(job_id, rows), daemon=True).start()
    return JobAccepted(
        job_id=job_id, questions=len(rows), status_url=f"/questionnaires/{job_id}"
    )


@app.get("/questionnaires", response_model=list[JobStatus])
def list_jobs(limit: int = 20) -> list[JobStatus]:
    return [
        JobStatus(job_id=j.id, progress=round(j.progress, 3), **_job_fields(j))
        for j in jobs.recent(jobs.connect(), limit)
    ]


def _job_fields(job: jobs.Job) -> dict:
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


@app.get("/questionnaires/{job_id}", response_model=JobStatus)
def job_status(job_id: str) -> JobStatus:
    job = jobs.get(jobs.connect(), job_id)
    if not job:
        raise HTTPException(404, "no such job")
    return JobStatus(job_id=job.id, progress=round(job.progress, 3), **_job_fields(job))


@app.get("/questionnaires/{job_id}/answers", response_model=list[Answer])
def job_answers(job_id: str) -> list[Answer]:
    conn = jobs.connect()
    job = jobs.get(conn, job_id)
    if not job:
        raise HTTPException(404, "no such job")

    graph = build_graph(index(), checkpointer=open_checkpointer())
    return [
        answer_for(graph, qid, _question_text(graph, qid))
        for qid in jobs.question_ids(conn, job_id)
    ]


def _question_text(graph, question_id: str) -> str:
    return (graph.get_state(thread_config(question_id)).values or {}).get(
        "question", ""
    )


@app.get("/reviews", response_model=list[Answer])
def reviews() -> list[Answer]:
    """Everything parked at the human-review interrupt, across all jobs."""
    conn = jobs.connect()
    graph = build_graph(index(), checkpointer=open_checkpointer())

    out: list[Answer] = []
    for job in jobs.recent(conn, limit=100):
        for qid in jobs.question_ids(conn, job.id):
            snapshot = graph.get_state(thread_config(qid))
            if snapshot.next == ("human_review",):
                out.append(
                    answer_for(graph, qid, (snapshot.values or {}).get("question", ""))
                )
    return out


@app.post("/reviews/{question_id}/approve", response_model=Answer)
def approve(
    question_id: str, decision: Annotated[ReviewDecision, Body()] = ReviewDecision()
) -> Answer:
    action = (
        {"action": "edit", "answer": decision.answer}
        if decision.answer
        else {"action": "approve"}
    )
    return _decide(question_id, action)


@app.post("/reviews/{question_id}/reject", response_model=Answer)
def reject(
    question_id: str, decision: Annotated[ReviewDecision, Body()] = ReviewDecision()
) -> Answer:
    return _decide(question_id, {"action": "reject", "reason": decision.reason})


def _decide(question_id: str, action: dict) -> Answer:
    checkpointer = open_checkpointer()
    graph = build_graph(index(), checkpointer=checkpointer)
    snapshot = graph.get_state(thread_config(question_id))
    if not snapshot.values:
        raise HTTPException(404, "no such question")
    if snapshot.next != ("human_review",):
        raise HTTPException(409, "this question is not awaiting review")

    resume(question_id, action, index(), checkpointer)
    return answer_for(graph, question_id, snapshot.values.get("question", ""))


@app.get("/controls/{label}")
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


@app.get("/gaps")
def gaps(confirmed_only: bool = False) -> dict:
    """Controls with no policy section behind them, by family.

    `confirmed_only=true` is the honest number: an unconfirmed machine proposal
    is not coverage.
    """
    conn = ontology_connect()
    clause = "AND s.confirmed_by IS NOT NULL" if confirmed_only else ""
    rows = conn.execute(
        f"""
        SELECT f.title AS family, COUNT(*) AS missing
        FROM control c JOIN control_family f ON f.id = c.family_id
        WHERE c.parent_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM satisfies s WHERE s.control_id = c.id {clause})
        GROUP BY f.title ORDER BY missing DESC
        """
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
