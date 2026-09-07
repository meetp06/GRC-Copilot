"""What every run cost and where the time went.

    python -m src.api.telemetry            # summary
    python -m src.api.telemetry slow 10    # the ten slowest questions

One row per answered question:

    question ─▶ retrieve ─▶ draft ─▶ verify ─▶ row written here
                  (ms)      (ms,$)   (ms,$)

Three reasons this exists rather than a log file:

  cost      An LLM system's spend is invisible until something is aggregating
            it. Per-question tokens are already in graph state; nothing was
            summing them across runs, so "what did last week cost" had no
            answer.

  latency   Knowing a question took 4 seconds is useless. Knowing the verifier
            took 2.6 of them is what tells you where to spend effort -- and the
            verifier is the step whose value ADR-0010 recorded as unproven.

  refusals  A rising refusal rate means the corpus stopped covering what people
            ask, which is a product signal rather than an error. Nothing throws
            when that happens.

Deliberately no prompt or answer text. This table gets read in a support
session, and CLAUDE.md's rule about never logging documents applies to durable
state as much as to log lines. Everything here is numbers and identifiers.
"""

from __future__ import annotations

import sqlite3
import statistics
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from rich.console import Console

console = Console()

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "telemetry.sqlite"

# Nova Lite on-demand, us-east-1. Titan V2 embeddings at $0.02/M.
COST_IN, COST_OUT, COST_EMBED = 0.06e-6, 0.24e-6, 0.02e-6

SCHEMA = """
CREATE TABLE IF NOT EXISTS run (
    id            INTEGER PRIMARY KEY,
    at            TEXT NOT NULL,
    job_id        TEXT,
    question_id   TEXT NOT NULL,
    -- outcome, not content
    status        TEXT NOT NULL,
    answerable    INTEGER,
    verified      INTEGER,
    revisions     INTEGER NOT NULL DEFAULT 0,
    confidence    TEXT,
    citations     INTEGER NOT NULL DEFAULT 0,
    -- where the time went
    total_ms      INTEGER NOT NULL,
    retrieve_ms   INTEGER,
    draft_ms      INTEGER,
    verify_ms     INTEGER,
    -- what it cost
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    usd           REAL NOT NULL DEFAULT 0.0
);
CREATE INDEX IF NOT EXISTS idx_run_at ON run(at);
CREATE INDEX IF NOT EXISTS idx_run_job ON run(job_id);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def usd(input_tokens: int, output_tokens: int) -> float:
    return input_tokens * COST_IN + output_tokens * COST_OUT


@contextmanager
def timed():
    """Wall-clock milliseconds for a block.

    perf_counter rather than time(): it is monotonic, so an NTP correction
    mid-run cannot produce a negative duration.
    """
    start = perf_counter()
    elapsed: dict[str, int] = {}
    try:
        yield elapsed
    finally:
        elapsed["ms"] = int((perf_counter() - start) * 1000)


def record(
    conn: sqlite3.Connection,
    state: dict,
    total_ms: int,
    *,
    job_id: str | None = None,
    stage_ms: dict[str, int] | None = None,
) -> None:
    """Write one row from a finished graph state. Never raises into the caller.

    Telemetry that can break a run is worse than no telemetry, so a failure here
    is swallowed: the answer has already been produced and paid for.
    """
    stage_ms = stage_ms or {}
    try:
        conn.execute(
            """
            INSERT INTO run (at, job_id, question_id, status, answerable, verified,
                             revisions, confidence, citations, total_ms, retrieve_ms,
                             draft_ms, verify_ms, input_tokens, output_tokens, usd)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                datetime.now(UTC).isoformat(timespec="seconds"),
                job_id,
                state.get("question_id", "unknown"),
                state.get("status", "unknown"),
                int(bool(state.get("answerable"))),
                int(bool(state.get("verified"))),
                state.get("revision_count", 0),
                state.get("confidence"),
                len(state.get("citations", [])),
                total_ms,
                stage_ms.get("retrieve"),
                stage_ms.get("draft"),
                stage_ms.get("verify"),
                state.get("input_tokens", 0),
                state.get("output_tokens", 0),
                usd(state.get("input_tokens", 0), state.get("output_tokens", 0)),
            ),
        )
        conn.commit()
    except sqlite3.Error:
        pass


def summary(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT * FROM run").fetchall()
    if not rows:
        return {"runs": 0}

    times = sorted(r["total_ms"] for r in rows)
    answered = [r for r in rows if r["answerable"]]
    return {
        "runs": len(rows),
        "usd_total": sum(r["usd"] for r in rows),
        "usd_per_question": sum(r["usd"] for r in rows) / len(rows),
        "median_ms": statistics.median(times),
        # p95, not mean: an average latency hides the tail, and the tail is what
        # a user waiting on a 200-question run actually experiences.
        "p95_ms": times[min(len(times) - 1, int(len(times) * 0.95))],
        "refusal_rate": 1 - len(answered) / len(rows),
        "verified_rate": sum(1 for r in rows if r["verified"]) / len(rows),
        "revisions_used": sum(r["revisions"] for r in rows),
        "uncited_answers": sum(1 for r in answered if r["citations"] == 0),
    }


def print_summary(conn: sqlite3.Connection) -> None:
    s = summary(conn)
    if not s["runs"]:
        console.print("[yellow]no runs recorded yet[/yellow]")
        return

    console.print(f"\n[bold]{s['runs']} questions answered[/bold]\n")
    console.print(f"  cost total        ${s['usd_total']:.4f}")
    console.print(f"  cost per question ${s['usd_per_question']:.6f}")
    console.print(f"  latency median    {s['median_ms']:.0f} ms")
    console.print(f"  latency p95       {s['p95_ms']:.0f} ms")
    console.print(f"  refusal rate      {s['refusal_rate']:.0%}")
    console.print(f"  verified          {s['verified_rate']:.0%}")
    console.print(f"  revisions used    {s['revisions_used']}")
    console.print(f"  uncited answers   {s['uncited_answers']}")

    stages = conn.execute(
        "SELECT AVG(retrieve_ms) r, AVG(draft_ms) d, AVG(verify_ms) v FROM run "
        "WHERE retrieve_ms IS NOT NULL"
    ).fetchone()
    if stages and stages["r"] is not None:
        console.print(
            f"\n  where the time goes: retrieve {stages['r']:.0f} ms, "
            f"draft {stages['d']:.0f} ms, verify {stages['v']:.0f} ms"
        )


def print_slowest(conn: sqlite3.Connection, limit: int = 10) -> None:
    rows = conn.execute(
        "SELECT question_id, status, total_ms, revisions, usd FROM run "
        "ORDER BY total_ms DESC LIMIT ?",
        (limit,),
    ).fetchall()
    console.print(f"\n[bold]Slowest {len(rows)}[/bold]\n")
    for r in rows:
        console.print(
            f"  {r['total_ms']:>6} ms  {r['question_id']:<12} {r['status']:<14} "
            f"rev={r['revisions']}  ${r['usd']:.6f}"
        )


def main() -> None:
    conn = connect()
    if len(sys.argv) > 1 and sys.argv[1] == "slow":
        print_slowest(conn, int(sys.argv[2]) if len(sys.argv) > 2 else 10)
    else:
        print_summary(conn)


if __name__ == "__main__":
    main()
