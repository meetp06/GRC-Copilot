"""Pick the storage backend once, from the environment.

    local (default)          Lambda
    ─────────────────        ──────────────────────
    SQLite jobs.sqlite  ──▶  DynamoDB jobs table
    SQLite runs.sqlite  ──▶  DynamoDB checkpoints table
    index on disk       ──▶  index downloaded from S3

One switch, read once, rather than an `if os.environ.get(...)` at every call
site. `src/api/main.py` asks this module for a store and never learns which one
it got.

The selector is the presence of `JOBS_TABLE`, not an explicit `ENV=lambda` flag.
Terraform sets it on the function; nothing sets it locally. A flag would be a
second thing to keep in step, and the failure mode of getting it wrong is
writing customer data to the wrong place.
"""

from __future__ import annotations

import functools
import os
import shutil
import tempfile
from pathlib import Path

from src.api import jobs as sqlite_jobs


def on_lambda() -> bool:
    return bool(os.environ.get("JOBS_TABLE"))


class SqliteJobStore:
    """The local backend, wrapped to match the DynamoDB store's shape.

    The SQLite functions take a connection as their first argument because they
    were written before there was a second backend. Rather than change every
    call site, the connection is held here.
    """

    def __init__(self) -> None:
        self.conn = sqlite_jobs.connect()

    def create(self, filename: str, question_ids: list[str]) -> str:
        return sqlite_jobs.create(self.conn, filename, question_ids)

    def mark(self, job_id: str, **fields) -> None:
        # The SQLite version assigns counters; the DynamoDB one adds to them.
        # Absolute values are what the worker computes, so convert here and keep
        # the difference inside the store rather than in the caller.
        sqlite_jobs.mark(self.conn, job_id, **fields)

    def finish(self, job_id: str, status: str, error: str | None = None) -> None:
        sqlite_jobs.finish(self.conn, job_id, status, error)

    def get(self, job_id: str):
        return sqlite_jobs.get(self.conn, job_id)

    def question_ids(self, job_id: str) -> list[str]:
        return sqlite_jobs.question_ids(self.conn, job_id)

    def recent(self, limit: int = 20):
        return sqlite_jobs.recent(self.conn, limit)

    @property
    def counters_are_additive(self) -> bool:
        return False


@functools.lru_cache(maxsize=1)
def job_store():
    """The job store for this process."""
    if on_lambda():
        from src.aws.jobs_dynamodb import DynamoJobStore

        store = DynamoJobStore()
        store.counters_are_additive = True  # type: ignore[attr-defined]
        return store
    return SqliteJobStore()


def open_checkpointer():
    """The checkpointer for this process.

    Not cached: LangGraph's SQLite saver holds a connection, and the Lambda one
    holds a boto3 resource. Both are cheap to build and sharing a connection
    across the threads a batch run creates is the kind of thing that fails only
    under load.
    """
    if on_lambda():
        from src.aws.checkpointer import DynamoDBSaver

        return DynamoDBSaver()

    from src.graph.checkpoint import open_checkpointer as sqlite_checkpointer

    return sqlite_checkpointer()


@functools.lru_cache(maxsize=1)
def index_dir() -> Path:
    """Where the vector index lives, downloading it from S3 on Lambda.

    Downloaded to /tmp rather than bundled in the deployment package, because
    the index changes when the corpus does and rebuilding it should not require
    redeploying the function. /tmp survives between invocations on a warm
    container, so this is a cold-start cost, not a per-request one.
    """
    if not on_lambda():
        return Path(__file__).resolve().parents[2] / "data" / "index"

    import boto3

    bucket = os.environ["DOCUMENTS_BUCKET"]
    local = Path(tempfile.gettempdir()) / "index"
    local.mkdir(parents=True, exist_ok=True)

    s3 = boto3.client("s3")
    for name in ("real.npy", "real.json"):
        target = local / name
        if target.exists():
            continue  # warm container: already downloaded
        s3.download_file(bucket, f"index/{name}", str(target))
    return local


@functools.lru_cache(maxsize=1)
def ontology_path() -> Path:
    """Where the ontology database lives.

    On Lambda it is downloaded from S3 to /tmp and opened read-only in practice:
    control mappings are proposed by the ingestion pipeline, not by the request
    path. A write here would be lost on the next cold start, which is the honest
    reason the confirm endpoint is not exposed in the deployed API.
    """
    if not on_lambda():
        return (
            Path(__file__).resolve().parents[2]
            / "data"
            / "ontology"
            / "ontology.sqlite"
        )

    import boto3

    local = Path(tempfile.gettempdir()) / "ontology.sqlite"
    if not local.exists():
        s3 = boto3.client("s3")
        with tempfile.NamedTemporaryFile(delete=False) as staged:
            s3.download_fileobj(
                os.environ["DOCUMENTS_BUCKET"], "ontology/ontology.sqlite", staged
            )
        # Move into place only once complete, so a cold start racing another
        # cannot open a half-written database.
        shutil.move(staged.name, local)
    return local
