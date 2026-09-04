"""Answer a questionnaire question from retrieved policy text, with a forced schema.

    python -m src.rag.answer "Do you encrypt customer data at rest?"

Week 1 asked for JSON in the prompt and then dug it back out of the response
with string surgery: strip the markdown fence, find the outermost braces, hope.
It failed on a correct answer because the model prefixed <thinking>.

This uses a tool call instead. The tool's input schema *is* the answer shape, so
Bedrock rejects a response that does not match it. There is nothing left to
parse and nothing to fail on.

The schema carries `answerable` as a first-class field rather than letting the
model express refusal in prose. For a compliance product a refusal has to be
machine-readable: 'we cannot answer this' must route to a human, not ship to a
customer as an attestation.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import boto3

from src.rag.index import VectorIndex

DEFAULT_MODEL_ID = "amazon.nova-lite-v1:0"
TOP_K = 5

# Three sentences, chosen on the numbers rather than by taste. A full page of
# rules scored worse on this model (87% vs 91% answerable accuracy) and started
# leaking its own instruction text into answers. The one-sentence version scored
# best on accuracy but left 20% of answers with no citation, which is worthless
# in a product whose promise is that every answer survives an auditor.
# See evals/results/2026-09-03-*.json and ADR on prompt length.
SYSTEM_PROMPT = """Answer security questionnaire questions using only the policy \
extracts provided, never general knowledge. If the extracts do not state the fact \
asked for, set answerable to false -- being about the topic is not enough. Cite the \
number of every extract you used."""

ANSWER_TOOL: dict[str, Any] = {
    "toolSpec": {
        "name": "submit_answer",
        "description": "Submit the final answer to the questionnaire question.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "answerable": {
                        "type": "boolean",
                        "description": (
                            "True if the extracts contain the fact asked for. False "
                            "only if they do not -- including when they are about the "
                            "topic without stating the fact. A correct answer of 'No' "
                            "is still answerable: answerable describes whether the "
                            "extracts support an answer, not whether that answer is "
                            "positive."
                        ),
                    },
                    "answer": {
                        "type": "string",
                        "description": (
                            "The answer, drawn only from the extracts. Written as the "
                            "company being asked: say 'we' and 'our', never 'you' or "
                            "'your' -- this text is sent to the customer who asked. If "
                            "answerable is false, state plainly that the policy corpus "
                            "does not cover this."
                        ),
                    },
                    "citations": {
                        "type": "array",
                        "description": "Extract numbers used. Empty if not answerable.",
                        "items": {"type": "integer"},
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": (
                            "high: the extracts state the answer outright. "
                            "medium: the answer requires combining extracts. "
                            "low: the extracts are only indirectly related."
                        ),
                    },
                },
                "required": ["answerable", "answer", "citations", "confidence"],
            }
        },
    }
}


@dataclass(frozen=True)
class Answer:
    answerable: bool
    answer: str
    citations: list[int]
    confidence: str
    retrieved: list[tuple[str, str]]  # (source, section) in the order shown
    input_tokens: int
    output_tokens: int

    @property
    def cited_chunks(self) -> list[tuple[str, str]]:
        """Citations resolved to (source, section). Out-of-range numbers are dropped."""
        return [
            self.retrieved[i - 1]
            for i in self.citations
            if 1 <= i <= len(self.retrieved)
        ]

    @property
    def usd_cost(self) -> float:
        # Nova Lite on-demand, us-east-1.
        return self.input_tokens * 0.06e-6 + self.output_tokens * 0.24e-6


def build_prompt(question: str, hits: list, critique: str | None = None) -> str:
    extracts = "\n\n".join(
        f"[{i}] {h.source} :: {h.section}\n{h.text}"
        for i, h in enumerate(hits, start=1)
    )
    prompt = f"POLICY EXTRACTS\n\n{extracts}\n\nQUESTION\n\n{question}"
    if critique:
        prompt += (
            f"\n\nA REVIEWER REJECTED YOUR PREVIOUS ANSWER\n\n{critique}\n\n"
            "Write a new answer that fixes this. If the extracts genuinely do not "
            "support an answer, set answerable to false rather than trying again."
        )
    return prompt


def answer_question(
    question: str,
    index: VectorIndex,
    *,
    top_k: int = TOP_K,
    model_id: str | None = None,
    system_prompt: str | None = None,
) -> Answer:
    """Retrieve, then draft. The one-shot path, used by the CLI and the evals."""
    hits = index.search(question, top_k=top_k)
    return draft_answer(question, hits, model_id=model_id, system_prompt=system_prompt)


def draft_answer(
    question: str,
    hits: list,
    *,
    model_id: str | None = None,
    system_prompt: str | None = None,
    critique: str | None = None,
) -> Answer:
    """Draft an answer from passages already retrieved.

    Split out from answer_question so the graph can retrieve once and draft
    several times: a verifier that rejects a draft sends it back here with a
    critique, and re-running retrieval on every attempt would pay for the same
    embedding repeatedly and could return different passages mid-loop.

    `critique` is the verifier's complaint about the previous attempt. It is
    appended to the user message rather than the system prompt, because it is
    feedback about this specific draft, not a standing rule.
    """
    model_id = model_id or os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)
    client = boto3.client(
        "bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1")
    )

    response = client.converse(
        modelId=model_id,
        system=[{"text": system_prompt or SYSTEM_PROMPT}],
        messages=[
            {
                "role": "user",
                "content": [{"text": build_prompt(question, hits, critique)}],
            }
        ],
        toolConfig={
            "tools": [ANSWER_TOOL],
            # Force the tool. Without this the model may reply in prose and we are
            # back to parsing, which is the whole thing being removed here.
            "toolChoice": {"tool": {"name": "submit_answer"}},
        },
        inferenceConfig={"maxTokens": 800, "temperature": 0.0},
    )

    payload = _extract_tool_input(response)
    usage = response["usage"]
    return Answer(
        answerable=bool(payload["answerable"]),
        answer=str(payload["answer"]),
        citations=[int(c) for c in payload.get("citations", [])],
        confidence=str(payload["confidence"]),
        retrieved=[(h.source, h.section) for h in hits],
        input_tokens=usage["inputTokens"],
        output_tokens=usage["outputTokens"],
    )


def _extract_tool_input(response: dict[str, Any]) -> dict[str, Any]:
    for block in response["output"]["message"]["content"]:
        if "toolUse" in block:
            return block["toolUse"]["input"]
    raise ValueError(
        "model returned no tool call despite toolChoice forcing one; "
        f"stopReason={response.get('stopReason')}"
    )


def main() -> None:
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    if len(sys.argv) < 2:
        print('Usage: python -m src.rag.answer "your question here"')
        raise SystemExit(1)

    result = answer_question(" ".join(sys.argv[1:]), VectorIndex.load())
    print(
        json.dumps(
            {
                "answerable": result.answerable,
                "confidence": result.confidence,
                "answer": result.answer,
                "cited": [f"{s} :: {sec}" for s, sec in result.cited_chunks],
                "cost_usd": round(result.usd_cost, 6),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
