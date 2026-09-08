"""Job records in DynamoDB, mirroring src/api/jobs.py.

Same function names and the same `Job` dataclass, so `src/api/main.py` imports
one or the other and nothing else changes. The switch is in
`src/api/store.py`.

One item per job. The question ids live on the job item as a list rather than as
separate items: a questionnaire is capped at 500 questions, ids are short, and
the whole list is read together every time it is read at all. Separate items
would be a second query for no benefit.

Two things differ from the SQLite version, both because DynamoDB is not SQL:

  Counters are updated with ADD rather than read-modify-write. The worker
  updates `completed` after every question; reading the row, incrementing, and
  writing it back would lose increments if two workers ever ran the same job.

  `recent()` scans. It is bounded by a small page and used only by an operator
  listing jobs, and adding a global secondary index to sort by created_at costs
  storage on every write to make one rare query fast. Noted rather than solved.

Job rows hold counts, status and timings — never questionnaire text. The same
rule as the SQLite version and for the same reason.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import boto3

from src.api.jobs import Job, JobStatus


class DynamoJobStore:
    def __init__(
        self, table_name: str | None = None, region: str | None = None
    ) -> None:
        resource = boto3.resource(
            "dynamodb", region_name=region or os.environ.get("AWS_REGION", "us-east-1")
        )
        self.table = resource.Table(table_name or os.environ["JOBS_TABLE"])

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")

    def create(self, filename: str, question_ids: list[str]) -> str:
        job_id = uuid.uuid4().hex[:12]
        self.table.put_item(
            Item={
                "job_id": job_id,
                "filename": filename,
                "status": "accepted",
                "total": len(question_ids),
                "completed": 0,
                "needs_review": 0,
                "failed": 0,
                "created_at": self._now(),
                "question_ids": question_ids,
            }
        )
        return job_id

    def mark(self, job_id: str, **fields) -> None:
        """Set status/error/finished_at, and ADD to the counters.

        The counters are additive rather than assigned, so a worker reporting
        progress cannot clobber another's increment. The caller passes the
        absolute value it wants for status-like fields and a delta for counters,
        which is why the two are split here.
        """
        allowed_set = {"status", "error", "finished_at"}
        allowed_add = {"completed", "needs_review", "failed"}

        sets = {k: v for k, v in fields.items() if k in allowed_set}
        adds = {k: v for k, v in fields.items() if k in allowed_add}
        if not sets and not adds:
            return

        expressions, names, values = [], {}, {}
        if sets:
            assignments = []
            for i, (key, value) in enumerate(sets.items()):
                # "status" is a DynamoDB reserved word; alias every name rather
                # than special-casing the ones that happen to be reserved today.
                names[f"#s{i}"], values[f":s{i}"] = key, value
                assignments.append(f"#s{i} = :s{i}")
            expressions.append("SET " + ", ".join(assignments))
        if adds:
            additions = []
            for i, (key, value) in enumerate(adds.items()):
                names[f"#a{i}"], values[f":a{i}"] = key, value
                additions.append(f"#a{i} :a{i}")
            expressions.append("ADD " + ", ".join(additions))

        self.table.update_item(
            Key={"job_id": job_id},
            UpdateExpression=" ".join(expressions),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    def finish(self, job_id: str, status: JobStatus, error: str | None = None) -> None:
        self.mark(job_id, status=status, error=error, finished_at=self._now())

    def get(self, job_id: str) -> Job | None:
        item = self.table.get_item(Key={"job_id": job_id}).get("Item")
        return self._to_job(item) if item else None

    def question_ids(self, job_id: str) -> list[str]:
        item = self.table.get_item(
            Key={"job_id": job_id}, ProjectionExpression="question_ids"
        ).get("Item")
        return list(item.get("question_ids", [])) if item else []

    def recent(self, limit: int = 20) -> list[Job]:
        response = self.table.scan(Limit=max(limit * 2, 40))
        jobs = [self._to_job(i) for i in response.get("Items", [])]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)[:limit]

    @staticmethod
    def _to_job(item: dict) -> Job:
        # DynamoDB returns numbers as Decimal, which is correct for money and
        # wrong for a progress counter that gets divided.
        return Job(
            id=item["job_id"],
            filename=item.get("filename", ""),
            status=item.get("status", "accepted"),
            total=int(item.get("total", 0)),
            completed=int(item.get("completed", 0)),
            needs_review=int(item.get("needs_review", 0)),
            failed=int(item.get("failed", 0)),
            error=item.get("error"),
            created_at=item.get("created_at", ""),
            finished_at=item.get("finished_at"),
        )
