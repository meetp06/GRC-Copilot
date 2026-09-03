"""Thin wrapper around the Bedrock Converse API.

Kept deliberately small. The point of week 1 is that you can read every line of the
agent loop and know exactly what is sent to the model and what comes back.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import boto3
from botocore.config import Config


@dataclass
class Usage:
    """Running token count for a single agent run.

    Why this exists: the #1 way to get a surprise LLM bill is an agent that loops
    without anyone watching the meter. See MISTAKES.md.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    per_call: list[dict[str, int]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, usage: dict[str, Any]) -> None:
        self.input_tokens += usage.get("inputTokens", 0)
        self.output_tokens += usage.get("outputTokens", 0)
        self.calls += 1
        self.per_call.append(
            {
                "input": usage.get("inputTokens", 0),
                "output": usage.get("outputTokens", 0),
            }
        )

    def summary(self) -> str:
        return (
            f"{self.calls} model call(s) | "
            f"in={self.input_tokens} out={self.output_tokens} total={self.total} tokens"
        )


class BedrockClient:
    def __init__(self, model_id: str | None = None, region: str | None = None) -> None:
        self.model_id = model_id or os.environ["BEDROCK_MODEL_ID"]
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")

        # Retries matter: Bedrock throttles. Without backoff a transient 429 kills a run.
        # boto3's "adaptive" mode adds client-side rate limiting on top of exponential backoff.
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=self.region,
            config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
        )

    def converse(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        """One turn with the model.

        Returns the raw Bedrock response. The caller inspects `stopReason`:
          - "end_turn"  -> the model produced a final answer
          - "tool_use"  -> the model wants a tool executed
          - "max_tokens" -> ran out of room (a bug signal, not a normal path)
        """
        kwargs: dict[str, Any] = {
            "modelId": self.model_id,
            "messages": messages,
            "system": [{"text": system}],
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
        }
        if tools:
            kwargs["toolConfig"] = {"tools": tools}

        return self._client.converse(**kwargs)
