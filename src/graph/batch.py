"""Run a whole questionnaire. One question is a demo; a questionnaire is the product.

    python -m src.graph.batch run    data/questionnaires/sample.csv
    python -m src.graph.batch report data/questionnaires/sample.csv
    python -m src.graph.batch export data/questionnaires/sample.csv answers.csv

Each question is its own checkpoint thread, so a batch is N independently
resumable runs rather than one long job. That has three consequences worth
stating, because they are the reason the batch layer is thin:

  A question paused for a human does not block the rest of the batch.
  A crash at question 40 does not restart questions 1 to 39.
  Re-running the same file skips everything already finished, and pays nothing
  for it. Re-doing work you already bought is the most expensive bug class in
  an LLM system.

Concurrency is bounded and deliberately low. Bedrock throttles, a throttled
call still costs wall-clock time in retries, and the failure mode of setting
this too high is a slower run rather than a faster one.
"""

from __future__ import annotations

import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from botocore.config import Config
from rich.console import Console

from src.graph.build import build_graph
from src.graph.checkpoint import open_checkpointer, thread_config
from src.rag.index import VectorIndex

console = Console()

# Measured rather than guessed. Nova Lite on-demand, us-east-1, 50 questions:
#
#   concurrency  4   17.2s   0.86s/question   0 retries, 0 errors
#   concurrency 20   15.7s   0.31s/question   0 retries, 0 errors
#   concurrency 50   10.7s   0.21s/question   0 retries, 0 errors
#
# No throttling at any of these, which contradicts the week 3 plan's assumption
# that it would appear early. 20 is the knee: 4 -> 20 is a 2.2x speedup, 20 ->
# 50 only 1.5x more, and the account's real limit is shared, undocumented, and
# would be discovered by a production run rather than by this one.
DEFAULT_CONCURRENCY = 20

# Nova Lite on-demand, us-east-1.
COST_IN, COST_OUT = 0.06e-6, 0.24e-6

# boto3's default retry policy gives up quickly. `adaptive` backs off on
# throttling and slows the client down rather than hammering a busy endpoint,
# which is what a bounded pool needs.
BOTO_CONFIG = Config(retries={"max_attempts": 6, "mode": "adaptive"})


def read_questionnaire(path: Path) -> list[dict]:
    """Read a questionnaire CSV. Requires `id` and `question` columns."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    missing = [r for r in rows if not r.get("id") or not r.get("question")]
    if missing:
        raise SystemExit(f"{path}: every row needs an id and a question column")
    return rows


def already_done(app, question_id: str) -> dict | None:
    """The finished state for a question, or None if it never ran or is paused.

    This is what makes a re-run cheap. A question that reached a terminal status
    is skipped entirely -- no retrieval, no drafting, no spend.
    """
    snapshot = app.get_state(thread_config(question_id))
    values = snapshot.values
    if not values:
        return None
    if snapshot.next:  # parked at the interrupt, waiting on a human
        return None
    if values.get("status") in {"approved", "rejected"}:
        return values
    return None


def run_one(app, row: dict) -> tuple[str, str]:
    """Answer one question. Returns (id, outcome) for the progress line."""
    qid, question = row["id"], row["question"]
    if already_done(app, qid) is not None:
        return qid, "skipped"
    out = app.invoke(
        {"question": question, "question_id": qid, "status": "retrieving"},
        config=thread_config(qid),
    )
    if "__interrupt__" in out:
        return qid, "needs_review"
    return qid, out.get("status", "unknown")


def run(path: Path, concurrency: int = DEFAULT_CONCURRENCY) -> None:
    rows = read_questionnaire(path)
    index = VectorIndex.load()
    app = build_graph(index, checkpointer=open_checkpointer())

    started = time.monotonic()
    outcomes: dict[str, str] = {}
    errors: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(run_one, app, row): row["id"] for row in rows}
        for future in as_completed(futures):
            qid = futures[future]
            try:
                _, outcome = future.result()
                outcomes[qid] = outcome
            except Exception as exc:  # one bad question must not lose the batch
                errors[qid] = f"{type(exc).__name__}: {exc}"
                outcomes[qid] = "error"

    elapsed = time.monotonic() - started
    console.print(
        f"\n{len(rows)} questions in {elapsed:.0f}s at concurrency {concurrency}"
    )
    if errors:
        console.print(f"[red]{len(errors)} failed[/red]")
        for qid, message in errors.items():
            console.print(f"  {qid}: {message}")
    report(path)


def collect(path: Path) -> list[dict]:
    """Current state of every question in the file, from the checkpoint database."""
    rows = read_questionnaire(path)
    app = build_graph(VectorIndex.load(), checkpointer=open_checkpointer())

    out: list[dict] = []
    for row in rows:
        snapshot = app.get_state(thread_config(row["id"]))
        values = snapshot.values or {}
        out.append(
            {
                "id": row["id"],
                "question": row["question"],
                "status": "not_run" if not values else values.get("status", "unknown"),
                "paused": bool(snapshot.next),
                "answer": values.get("draft", ""),
                "citations": [
                    f"{values['retrieved'][i - 1]['source']} :: "
                    f"{values['retrieved'][i - 1]['section']}"
                    for i in values.get("citations", [])
                    if 1 <= i <= len(values.get("retrieved", []))
                ],
                "confidence": values.get("confidence", ""),
                "reviewed_by_human": values.get("reviewed_by_human", False),
                "edited_by_human": values.get("edited_by_human", False),
                "revisions": values.get("revision_count", 0),
                "input_tokens": values.get("input_tokens", 0),
                "output_tokens": values.get("output_tokens", 0),
            }
        )
    return out


def report(path: Path) -> None:
    rows = collect(path)
    auto = [r for r in rows if r["status"] == "approved" and not r["reviewed_by_human"]]
    waiting = [r for r in rows if r["paused"]]
    human_ok = [r for r in rows if r["reviewed_by_human"]]
    cited = [r for r in auto if r["citations"]]
    cost = sum(
        r["input_tokens"] * COST_IN + r["output_tokens"] * COST_OUT for r in rows
    )

    console.print(f"\n[bold]{path.name}[/bold]")
    console.print(f"  auto-answered      {len(auto)}/{len(rows)}")
    console.print(f"  with a citation    {len(cited)}/{len(auto) or 1}")
    console.print(f"  awaiting review    {len(waiting)}")
    console.print(f"  decided by human   {len(human_ok)}")
    console.print(f"  revisions used     {sum(r['revisions'] for r in rows)}")
    console.print(f"  cost               ${cost:.4f}")
    if waiting:
        console.print("\n  waiting:")
        for r in waiting:
            console.print(f"    {r['id']}  {r['question'][:60]}")


# Excel and Google Sheets evaluate a cell as a formula when it begins with one
# of these. A cell reading =cmd|'/c calc'!A1 can execute on the machine that
# opens the file, and DDE payloads have been used this way for real.
#
# This export is handed to a customer's security team, who open it in Excel, and
# CLAUDE.md says to treat questionnaire input as hostile: a formula planted in
# an uploaded question round-trips through here untouched, and a policy document
# under an attacker's control can steer the model into emitting one.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: object) -> str:
    """Neutralise a cell that a spreadsheet would treat as a formula.

    Prefixing with an apostrophe is the standard mitigation: spreadsheets read
    it as "this is text", show the original content, and never evaluate it.
    Quoting alone does not help -- a quoted cell is still parsed as a formula.
    """
    text = "" if value is None else str(value)
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def export(path: Path, out_path: Path) -> None:
    """Write answers back out, in a shape a person can paste into the buyer's sheet."""
    rows = collect(path)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "question",
                "answer",
                "citations",
                "status",
                "confidence",
                "reviewed_by_human",
                "edited_by_human",
            ],
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {
                    "id": csv_safe(r["id"]),
                    "question": csv_safe(r["question"]),
                    "answer": csv_safe(r["answer"]),
                    # Semicolons, not commas: these go in one CSV cell.
                    "citations": csv_safe("; ".join(r["citations"])),
                    "status": csv_safe(r["status"]),
                    "confidence": csv_safe(r["confidence"]),
                    "reviewed_by_human": r["reviewed_by_human"],
                    "edited_by_human": r["edited_by_human"],
                }
            )
    console.print(f"wrote {len(rows)} rows to {out_path}")


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    if len(sys.argv) < 3:
        console.print(__doc__)
        raise SystemExit(1)

    command, path = sys.argv[1], Path(sys.argv[2])
    if command == "run":
        concurrency = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_CONCURRENCY
        run(path, concurrency)
    elif command == "report":
        report(path)
    elif command == "export" and len(sys.argv) > 3:
        export(path, Path(sys.argv[3]))
    else:
        console.print(__doc__)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
