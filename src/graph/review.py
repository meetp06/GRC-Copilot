"""Human review queue: list what is waiting, inspect it, decide.

    python -m src.graph.review ask   q_042 "Do you support TLS 1.2?"
    python -m src.graph.review list
    python -m src.graph.review show  q_042
    python -m src.graph.review approve q_042
    python -m src.graph.review edit    q_042 "The corrected answer."
    python -m src.graph.review reject  q_042

Every command opens the checkpoint database fresh and exits. That is the point:
a run paused for a human is not held open by a live process, so the reviewer can
come back tomorrow, from a different terminal, after a crash or a reboot, and
the run continues from exactly where it stopped.

The reviewer sees the draft, the sections it cites, and the verifier's complaint
if there was one. A reviewer who has to open the corpus to check an answer is
not being helped, and an answer nobody can check is the thing this product
exists to prevent.
"""

from __future__ import annotations

import sys

from rich.console import Console

from src.graph.build import resume, start
from src.graph.checkpoint import open_checkpointer
from src.rag.index import VectorIndex

console = Console()


def _pending(checkpointer) -> list[tuple[str, dict]]:
    """Every run that stopped for a human, newest checkpoint per thread.

    Reads the checkpoint database rather than a separate queue table. There is
    no second source of truth to drift: a question is pending precisely because
    its graph is parked at the interrupt.
    """
    # checkpointer.list() returns newest first, and every step of a run is its
    # own checkpoint. Only the newest per thread is the current state.
    #
    # `visited` is deliberately separate from `pending`. An earlier version used
    # one dict for both, populated only when a checkpoint matched needs_review --
    # so a thread whose newest checkpoint was `rejected` was never marked seen,
    # and the older needs_review checkpoint behind it came back as pending. A
    # dedup set that only records the rows passing the filter does not dedup.
    visited: set[str] = set()
    pending: dict[str, dict] = {}
    for item in checkpointer.list(None):
        thread_id = item.config["configurable"]["thread_id"]
        if thread_id in visited:
            continue
        visited.add(thread_id)
        values = item.checkpoint.get("channel_values", {})
        if values.get("status") == "needs_review" and not values.get(
            "reviewed_by_human"
        ):
            pending[thread_id] = values
    return sorted(pending.items())


def cmd_list(checkpointer) -> None:
    rows = _pending(checkpointer)
    if not rows:
        console.print("[green]Nothing waiting for review.[/green]")
        return
    console.print(f"[bold]{len(rows)} awaiting review[/bold]\n")
    for thread_id, v in rows:
        reason = (
            "refused"
            if not v.get("answerable")
            else "failed verification"
            if not v.get("verified")
            else "unknown"
        )
        console.print(
            f"  [cyan]{thread_id}[/cyan]  ({reason})  {v.get('question', '')[:64]}"
        )


def cmd_show(checkpointer, question_id: str) -> None:
    match = dict(_pending(checkpointer)).get(question_id)
    if match is None:
        console.print(f"[yellow]{question_id} is not awaiting review.[/yellow]")
        return

    console.rule(question_id)
    console.print(f"[bold]Question[/bold]\n{match.get('question')}\n")
    console.print(f"[bold]Draft[/bold]\n{match.get('draft')}\n")

    cited = [
        f"{match['retrieved'][i - 1]['source']} :: {match['retrieved'][i - 1]['section']}"
        for i in match.get("citations", [])
        if 1 <= i <= len(match.get("retrieved", []))
    ]
    console.print("[bold]Cites[/bold]")
    console.print(
        "\n".join(f"  {c}" for c in cited) if cited else "  [red]nothing[/red]"
    )

    if match.get("critique"):
        console.print(f"\n[bold]Verifier rejected it[/bold]\n  {match['critique']}")
    console.print(
        f"\nanswerable={match.get('answerable')}  verified={match.get('verified')}  "
        f"revisions={match.get('revision_count', 0)}"
    )


def cmd_decide(checkpointer, index, question_id: str, decision: dict) -> None:
    state = resume(question_id, decision, index, checkpointer)
    console.print(
        f"[green]{question_id}[/green] -> [bold]{state.get('status')}[/bold]"
        + ("  (edited)" if state.get("edited_by_human") else "")
    )


def cmd_ask(checkpointer, index, question_id: str, question: str) -> None:
    out = start(question, question_id, index, checkpointer)
    if "__interrupt__" in out:
        payload = out["__interrupt__"][0].value
        console.print(f"[yellow]{question_id} needs review.[/yellow]")
        console.print(f"  draft: {payload.get('draft')}")
        console.print(f"  run: python -m src.graph.review show {question_id}")
    else:
        console.print(
            f"[green]{question_id} auto-approved.[/green]\n  {out.get('draft')}"
        )


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    if len(sys.argv) < 2:
        console.print(__doc__)
        raise SystemExit(1)

    command, args = sys.argv[1], sys.argv[2:]
    checkpointer = open_checkpointer()

    if command == "list":
        cmd_list(checkpointer)
        return
    if command == "show" and args:
        cmd_show(checkpointer, args[0])
        return

    index = VectorIndex.load()
    if command == "ask" and len(args) >= 2:
        cmd_ask(checkpointer, index, args[0], " ".join(args[1:]))
    elif command == "approve" and args:
        cmd_decide(checkpointer, index, args[0], {"action": "approve"})
    elif command == "reject" and args:
        cmd_decide(checkpointer, index, args[0], {"action": "reject"})
    elif command == "edit" and len(args) >= 2:
        cmd_decide(
            checkpointer,
            index,
            args[0],
            {"action": "edit", "answer": " ".join(args[1:])},
        )
    else:
        console.print(__doc__)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
