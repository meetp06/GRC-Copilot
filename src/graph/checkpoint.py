"""Durable graph state, so a paused run survives the process that started it.

This is the whole reason this project moved off a hand-written loop. A
questionnaire takes minutes to draft and then waits on a human, who might come
back in an hour or on Monday. The run has to survive that wait, and a crash
during it.

LangGraph writes the full QuestionState to SQLite after every node. Each
question gets a `thread_id`, and resuming means handing the graph that id: it
reads the last checkpoint and continues from the node after the one that
finished. Nodes already completed are not re-run, so a resumed run does not pay
twice for work already bought.

That is also why `src/graph/state.py` holds only serialisable data. Anything in
state that SQLite cannot store breaks resume, which is the one feature the
framework was adopted for.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "data" / "runs.sqlite"


def open_checkpointer(path: Path | str | None = None) -> SqliteSaver:
    """Open (or create) the checkpoint database.

    `check_same_thread=False` because LangGraph may touch the connection from a
    worker thread during a batch run. SQLite serialises writes itself, and the
    alternative -- a connection per thread -- would mean several writers racing
    on one file, which is worse.
    """
    db_path = Path(path) if path else DEFAULT_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    return SqliteSaver(conn)


def thread_config(question_id: str) -> dict:
    """The handle a run is resumed by.

    One thread per question, keyed by the question's id, so a batch of 50
    questions is 50 independent resumable runs rather than one run that must
    restart as a whole.
    """
    return {"configurable": {"thread_id": question_id}}
