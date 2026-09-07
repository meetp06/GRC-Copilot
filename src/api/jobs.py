"""Job records for questionnaire runs, in SQLite.

A 200-question run takes minutes. An HTTP request that blocks that long gets
killed by a load balancer, so the API accepts the work, returns a job id, and
runs it in a background thread. This module is the record of what was accepted
and how far it has got.

Deliberately a separate store from the LangGraph checkpointer:

  the checkpointer knows where one *question* is in the graph
  this table knows where one *questionnaire* is as a unit of work

Mixing them would mean querying LangGraph's internal schema to answer "is my
upload finished", which couples the API to a library's storage layout.

Job rows never hold questionnaire text. Only counts, status and timings, so this
file can be read in a support session without exposing customer content --
CLAUDE.md's rule about not logging documents applies to durable state too.
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "jobs.sqlite"

JobStatus = Literal["accepted", "running", "done", "failed"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS job (
    id           TEXT PRIMARY KEY,
    filename     TEXT NOT NULL,
    status       TEXT NOT NULL,
    total        INTEGER NOT NULL DEFAULT 0,
    completed    INTEGER NOT NULL DEFAULT 0,
    needs_review INTEGER NOT NULL DEFAULT 0,
    failed       INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    created_at   TEXT NOT NULL,
    finished_at  TEXT
);

-- Which question ids belong to which job. The answers themselves live in the
-- checkpointer; this is only the membership list, so /questionnaires/{id}/answers
-- knows what to look up.
CREATE TABLE IF NOT EXISTS job_question (
    job_id      TEXT NOT NULL REFERENCES job(id),
    question_id TEXT NOT NULL,
    PRIMARY KEY (job_id, question_id)
);
"""


@dataclass(frozen=True)
class Job:
    id: str
    filename: str
    status: JobStatus
    total: int
    completed: int
    needs_review: int
    failed: int
    error: str | None
    created_at: str
    finished_at: str | None

    @property
    def progress(self) -> float:
        return self.completed / self.total if self.total else 0.0


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the API thread creates the job and a worker
    # thread updates it. SQLite serialises writes itself.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def create(conn: sqlite3.Connection, filename: str, question_ids: list[str]) -> str:
    job_id = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO job (id, filename, status, total, created_at) VALUES (?, ?, ?, ?, ?)",
        (job_id, filename, "accepted", len(question_ids), _now()),
    )
    conn.executemany(
        "INSERT INTO job_question (job_id, question_id) VALUES (?, ?)",
        [(job_id, qid) for qid in question_ids],
    )
    conn.commit()
    return job_id


def mark(conn: sqlite3.Connection, job_id: str, **fields) -> None:
    """Update a job's counters or status. Only known columns are accepted."""
    allowed = {"status", "completed", "needs_review", "failed", "error", "finished_at"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    assignments = ", ".join(f"{k} = ?" for k in updates)
    # nosec B608 - `assignments` is built only from keys that survived the
    # `allowed` filter above, so no caller-supplied string reaches the SQL. Every
    # value is a bound parameter. test_mark_ignores_unknown_columns pins this.
    conn.execute(
        f"UPDATE job SET {assignments} WHERE id = ?",  # nosec B608
        [*updates.values(), job_id],
    )
    conn.commit()


def finish(
    conn: sqlite3.Connection, job_id: str, status: JobStatus, error: str | None = None
) -> None:
    mark(conn, job_id, status=status, error=error, finished_at=_now())


def get(conn: sqlite3.Connection, job_id: str) -> Job | None:
    row = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    return Job(**dict(row)) if row else None


def question_ids(conn: sqlite3.Connection, job_id: str) -> list[str]:
    return [
        r["question_id"]
        for r in conn.execute(
            "SELECT question_id FROM job_question WHERE job_id = ? ORDER BY rowid",
            (job_id,),
        )
    ]


def recent(conn: sqlite3.Connection, limit: int = 20) -> list[Job]:
    rows = conn.execute(
        "SELECT * FROM job ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [Job(**dict(r)) for r in rows]
