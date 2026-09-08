"""A LangGraph checkpointer backed by DynamoDB.

Written rather than taken from a dependency. `langgraph-checkpoint-dynamodb` on
PyPI is at 0.1.0 with a single release, and this is the component that decides
whether a paused questionnaire survives — ADR-0009 says durable state with
interrupts is the entire reason this project adopted a framework. A one-release
package holding customer questionnaire text is not a trade worth making, and the
interface is five methods.

    thread_id (partition)  "{job_id}:{question_id}"
    checkpoint_id (sort)   "{namespace}#{id}", newest last

Three decisions that are not obvious:

  **The sort key is namespace-prefixed.** LangGraph writes checkpoints under a
  checkpoint namespace for subgraphs. Without the prefix, two namespaces on one
  thread interleave in sort order and `get_tuple` returns whichever happens to
  sort last rather than the latest of the one asked for.

  **Pending writes are items, not a nested attribute.** A task's writes arrive
  after the checkpoint that owns them, and updating a nested list means a
  read-modify-write that two concurrent tasks can lose. Separate items make each
  write a single conditional-free PutItem.

  **Serialisation uses LangGraph's own serde, stored as Binary.** The serde
  handles types DynamoDB's document mapper will not, and storing the bytes
  opaquely means a LangGraph upgrade that changes the format is their problem to
  version, not a silent decode error here.

Every item carries `expires_at`. DynamoDB's TTL removes abandoned runs, which
matters because checkpoints hold questionnaire text and retrieved policy
extracts — see docs/THREAT-MODEL.md T3.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)

# A questionnaire waiting on a human should not wait forever, and an abandoned
# one should not hold customer text indefinitely.
DEFAULT_TTL_DAYS = 30

# Separates the namespace from the checkpoint id in the sort key. "#" cannot
# appear in either, so the split is unambiguous.
SEP = "#"


class DynamoDBSaver(BaseCheckpointSaver):
    """Checkpoints in DynamoDB, one item per checkpoint plus one per write."""

    def __init__(
        self,
        table_name: str | None = None,
        *,
        region: str | None = None,
        ttl_days: int = DEFAULT_TTL_DAYS,
    ) -> None:
        super().__init__()
        self.table_name = table_name or os.environ["CHECKPOINTS_TABLE"]
        self.ttl_days = ttl_days
        resource = boto3.resource(
            "dynamodb", region_name=region or os.environ.get("AWS_REGION", "us-east-1")
        )
        self.table = resource.Table(self.table_name)

    # --- helpers ----------------------------------------------------------

    def _expiry(self) -> int:
        return int((datetime.now(UTC) + timedelta(days=self.ttl_days)).timestamp())

    @staticmethod
    def _sort_key(namespace: str, checkpoint_id: str) -> str:
        return f"{namespace}{SEP}{checkpoint_id}"

    @staticmethod
    def _split(sort_key: str) -> tuple[str, str]:
        namespace, _, checkpoint_id = sort_key.rpartition(SEP)
        return namespace, checkpoint_id

    def _config(self, thread_id: str, namespace: str, checkpoint_id: str) -> dict:
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": namespace,
                "checkpoint_id": checkpoint_id,
            }
        }

    def _writes_for(
        self, thread_id: str, namespace: str, checkpoint_id: str
    ) -> list[tuple]:
        """Pending writes belonging to one checkpoint, in the order stored."""
        response = self.table.query(
            KeyConditionExpression=Key("thread_id").eq(thread_id)
            & Key("checkpoint_id").begins_with(
                f"{self._sort_key(namespace, checkpoint_id)}{SEP}write{SEP}"
            )
        )
        return [
            (
                item["task_id"],
                item["channel"],
                self.serde.loads_typed(
                    (item["write_type"], bytes(item["write_value"].value))
                ),
            )
            for item in sorted(
                response.get("Items", []), key=lambda i: i["checkpoint_id"]
            )
        ]

    # --- the interface ----------------------------------------------------

    def put(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> dict:
        configurable = config["configurable"]
        thread_id = configurable["thread_id"]
        namespace = configurable.get("checkpoint_ns", "")
        checkpoint_id = checkpoint["id"]

        checkpoint_type, checkpoint_bytes = self.serde.dumps_typed(checkpoint)
        metadata_type, metadata_bytes = self.serde.dumps_typed(dict(metadata))

        self.table.put_item(
            Item={
                "thread_id": thread_id,
                "checkpoint_id": self._sort_key(namespace, checkpoint_id),
                "namespace": namespace,
                "raw_checkpoint_id": checkpoint_id,
                # The id of the checkpoint this one follows, so `list` can walk
                # a thread's history backwards without re-sorting.
                "parent_checkpoint_id": configurable.get("checkpoint_id"),
                "checkpoint_type": checkpoint_type,
                "checkpoint": checkpoint_bytes,
                "metadata_type": metadata_type,
                "metadata": metadata_bytes,
                "expires_at": self._expiry(),
            }
        )
        return self._config(thread_id, namespace, checkpoint_id)

    def put_writes(
        self,
        config: dict,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        configurable = config["configurable"]
        thread_id = configurable["thread_id"]
        namespace = configurable.get("checkpoint_ns", "")
        checkpoint_id = configurable["checkpoint_id"]
        prefix = self._sort_key(namespace, checkpoint_id)

        with self.table.batch_writer() as batch:
            for index, (channel, value) in enumerate(writes):
                write_type, write_bytes = self.serde.dumps_typed(value)
                batch.put_item(
                    Item={
                        "thread_id": thread_id,
                        # Index is zero-padded so lexical order is write order.
                        # Without it, write 10 sorts before write 2.
                        "checkpoint_id": f"{prefix}{SEP}write{SEP}{task_id}{SEP}{index:04d}",
                        "task_id": task_id,
                        "task_path": task_path,
                        "channel": channel,
                        "write_type": write_type,
                        "write_value": write_bytes,
                        "expires_at": self._expiry(),
                    }
                )

    def get_tuple(self, config: dict) -> CheckpointTuple | None:
        configurable = config["configurable"]
        thread_id = configurable["thread_id"]
        namespace = configurable.get("checkpoint_ns", "")
        checkpoint_id = configurable.get("checkpoint_id")

        if checkpoint_id:
            response = self.table.get_item(
                Key={
                    "thread_id": thread_id,
                    "checkpoint_id": self._sort_key(namespace, checkpoint_id),
                }
            )
            item = response.get("Item")
        else:
            # Latest for this namespace. begins_with rather than a bare query,
            # because a thread can hold checkpoints for several namespaces and
            # the newest overall may belong to a different one.
            response = self.table.query(
                KeyConditionExpression=Key("thread_id").eq(thread_id)
                & Key("checkpoint_id").begins_with(f"{namespace}{SEP}"),
                ScanIndexForward=False,
                Limit=10,
            )
            item = next(
                (
                    i
                    for i in response.get("Items", [])
                    if SEP + "write" + SEP not in i["checkpoint_id"]
                ),
                None,
            )

        if item is None:
            return None
        return self._to_tuple(item)

    def _to_tuple(self, item: dict) -> CheckpointTuple:
        namespace = item.get("namespace", "")
        checkpoint_id = item["raw_checkpoint_id"]
        thread_id = item["thread_id"]

        parent = item.get("parent_checkpoint_id")
        return CheckpointTuple(
            config=self._config(thread_id, namespace, checkpoint_id),
            checkpoint=self.serde.loads_typed(
                (item["checkpoint_type"], bytes(item["checkpoint"].value))
            ),
            metadata=self.serde.loads_typed(
                (item["metadata_type"], bytes(item["metadata"].value))
            ),
            parent_config=self._config(thread_id, namespace, parent)
            if parent
            else None,
            pending_writes=self._writes_for(thread_id, namespace, checkpoint_id),
        )

    def list(
        self,
        config: dict | None,
        *,
        filter: dict[str, Any] | None = None,
        before: dict | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        """Checkpoints for one thread, newest first.

        A thread is required. Listing every thread means a full table scan, and
        the API's review queue asks per job, never globally -- see
        src/api/main.py, which iterates known job ids rather than scanning.
        """
        if not config or "thread_id" not in config.get("configurable", {}):
            raise ValueError("DynamoDBSaver.list requires a thread_id")

        thread_id = config["configurable"]["thread_id"]
        namespace = config["configurable"].get("checkpoint_ns", "")

        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("thread_id").eq(thread_id)
            & Key("checkpoint_id").begins_with(f"{namespace}{SEP}"),
            "ScanIndexForward": False,
        }
        if limit:
            # Over-fetch, because write items share the partition and are
            # filtered out below; asking for exactly `limit` would return fewer.
            kwargs["Limit"] = limit * 4

        for item in self.table.query(**kwargs).get("Items", []):
            if f"{SEP}write{SEP}" in item["checkpoint_id"]:
                continue
            if (
                before
                and item["raw_checkpoint_id"] >= before["configurable"]["checkpoint_id"]
            ):
                continue
            yield self._to_tuple(item)
            if limit:
                limit -= 1
                if limit <= 0:
                    return

    def delete_thread(self, thread_id: str) -> None:
        """Remove a thread and everything under it.

        Needed for a real deletion request: a customer asking for their data to
        be removed means the checkpoints too, and those hold the questionnaire
        text and the retrieved policy extracts.
        """
        response = self.table.query(
            KeyConditionExpression=Key("thread_id").eq(thread_id),
            ProjectionExpression="thread_id, checkpoint_id",
        )
        with self.table.batch_writer() as batch:
            for item in response.get("Items", []):
                batch.delete_item(
                    Key={
                        "thread_id": item["thread_id"],
                        "checkpoint_id": item["checkpoint_id"],
                    }
                )
