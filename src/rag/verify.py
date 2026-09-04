"""A separate agent that checks a draft answer against the passages it cites.

Week 2 measured why this has to exist. The refusal cascade -- the drafter's own
`answerable` flag plus a substring check for refusal language -- catches a lot,
but it has one blind spot, and it is the dangerous one:

    Retrieval returns vendor-management-policy.md, which says we require a
    SOC 2 Type II report from our vendors. The question asks whether WE hold
    one. If the drafter answers confidently from that passage, its flag says
    answerable and its text contains no refusal language. Both cheap signals
    agree, and both are wrong.

At evaluation time the golden set's band label catches that for free. At runtime
there is no label. Something else has to check, and it cannot be the model that
already convinced itself -- a drafter asked to re-read its own answer is being
asked to find a mistake it did not believe it was making.

So the verifier gets a different job, a different prompt, and no memory of
having written the draft. Its only question is whether each claim appears in the
cited text. It is not asked whether the answer is good.

The specific failure it hunts is subject drift: the claim is supported by words
that are present, but those words are about someone else. Standard faithfulness
checks -- token overlap, or entailment against the retrieved span -- pass the
SOC 2 case, because the string really is there.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import boto3

DEFAULT_MODEL_ID = "amazon.nova-lite-v1:0"

VERIFIER_PROMPT = """You check whether a draft answer is supported by the source \
extracts it cites. You did not write the draft and you are not improving it.

Break the draft into its separate factual claims. For each one, find the exact \
sentence in an extract that states it and quote that sentence verbatim. If no \
sentence states the claim, the quote must be empty and the claim is unsupported.

A claim is unsupported when:

- no extract states it, or
- an extract mentions the topic without stating this particular fact, or
- an extract states it about someone else. Text saying we require something of \
our vendors does not say we do it ourselves. Check who each sentence is about.

Do not reject a claim for being brief or plainly worded. Only reject claims the \
extracts do not support."""

# The schema is the guardrail, not the prompt -- ADR-0008. The first version of
# this tool asked for a single `supported` boolean and the verifier answered
# "true" to everything, including an answer claiming we hold a SOC 2 report
# sourced from a passage about our vendors.
#
# Requiring a verbatim quote per claim is what changed that. A boolean is cheap
# to agree with; a quote has to exist in the text, and `_quote_is_real` checks
# that it does. A claim whose quote is invented or empty is unsupported no
# matter what the model said about it.
VERIFY_TOOL: dict[str, Any] = {
    "toolSpec": {
        "name": "submit_verdict",
        "description": "Report, claim by claim, whether the draft is supported.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "claims": {
                        "type": "array",
                        "description": "Every factual claim in the draft, checked separately.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "claim": {
                                    "type": "string",
                                    "description": "One factual claim from the draft.",
                                },
                                "supporting_quote": {
                                    "type": "string",
                                    "description": (
                                        "The sentence from an extract that states this "
                                        "claim, copied word for word. Empty string if no "
                                        "sentence states it."
                                    ),
                                },
                                "about_us": {
                                    "type": "boolean",
                                    "description": (
                                        "Whether the quoted sentence is about this company. "
                                        "False if it is about vendors, customers, or anyone "
                                        "else."
                                    ),
                                },
                            },
                            "required": ["claim", "supporting_quote", "about_us"],
                        },
                    },
                    "critique": {
                        "type": "string",
                        "description": (
                            "One or two sentences telling the writer what to fix. Empty "
                            "if every claim is supported."
                        ),
                    },
                },
                "required": ["claims", "critique"],
            }
        },
    }
}


@dataclass(frozen=True)
class Verdict:
    supported: bool
    unsupported_claims: list[str]
    critique: str
    input_tokens: int
    output_tokens: int

    @property
    def usd_cost(self) -> float:
        return self.input_tokens * 0.06e-6 + self.output_tokens * 0.24e-6


def build_verify_prompt(question: str, draft: str, extracts: list[dict]) -> str:
    """Show the verifier only the passages the draft actually cited.

    Showing all five would let it justify a claim from a passage the drafter
    never used, which is how a citation check quietly stops checking citations.
    """
    body = "\n\n".join(
        f"[{i}] {e['source']} :: {e['section']}\n{e['text']}"
        for i, e in enumerate(extracts, start=1)
    )
    return (
        f"QUESTION\n\n{question}\n\n"
        f"DRAFT ANSWER\n\n{draft}\n\n"
        f"CITED EXTRACTS\n\n{body}"
    )


def verify_answer(
    question: str,
    draft: str,
    extracts: list[dict],
    *,
    model_id: str | None = None,
) -> Verdict:
    """Check a draft against its cited extracts."""
    if not extracts:
        # Nothing cited means nothing to check against. That is unsupported by
        # definition, and it costs nothing to say so without a model call.
        return Verdict(
            supported=False,
            unsupported_claims=[draft],
            critique="The answer cites no extract, so nothing supports it.",
            input_tokens=0,
            output_tokens=0,
        )

    model_id = model_id or os.environ.get("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID)
    client = boto3.client(
        "bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1")
    )

    response = client.converse(
        modelId=model_id,
        system=[{"text": VERIFIER_PROMPT}],
        messages=[
            {
                "role": "user",
                "content": [{"text": build_verify_prompt(question, draft, extracts)}],
            }
        ],
        toolConfig={
            "tools": [VERIFY_TOOL],
            "toolChoice": {"tool": {"name": "submit_verdict"}},
        },
        inferenceConfig={"maxTokens": 600, "temperature": 0.0},
    )

    payload = _extract_tool_input(response)
    usage = response["usage"]
    corpus = " ".join(e["text"] for e in extracts)

    unsupported: list[str] = []
    for item in payload.get("claims", []):
        quote = str(item.get("supporting_quote", "")).strip()
        if not quote:
            unsupported.append(str(item.get("claim", "")))
        elif not quote_is_real(quote, corpus):
            # The model produced a quote that is not in the source. That is a
            # fabricated citation, which is worse than admitting it found none.
            unsupported.append(str(item.get("claim", "")))
        elif not item.get("about_us", True):
            unsupported.append(str(item.get("claim", "")))

    claims = payload.get("claims", [])
    return Verdict(
        supported=bool(claims) and not unsupported,
        unsupported_claims=unsupported,
        critique=str(payload.get("critique", "")) or _default_critique(unsupported),
        input_tokens=usage["inputTokens"],
        output_tokens=usage["outputTokens"],
    )


def normalise(text: str) -> str:
    """Collapse whitespace and case so a quote can be matched against the source."""
    return " ".join(text.lower().split())


def quote_is_real(quote: str, corpus: str) -> bool:
    """Is this quote actually present in the cited text?

    This is the check that makes the schema worth anything. Asking for a quote
    only helps if something confirms the quote exists -- otherwise the model can
    invent a supporting sentence as easily as it can say `supported: true`.

    Matching is on normalised whitespace and case, not exact bytes, because
    models routinely re-punctuate or drop a trailing period when copying.
    """
    return normalise(quote) in normalise(corpus)


def _default_critique(unsupported: list[str]) -> str:
    if not unsupported:
        return ""
    return "These claims are not stated in the cited extracts: " + "; ".join(
        unsupported
    )


def _extract_tool_input(response: dict[str, Any]) -> dict[str, Any]:
    for block in response["output"]["message"]["content"]:
        if "toolUse" in block:
            return block["toolUse"]["input"]
    raise ValueError(
        "verifier returned no tool call despite toolChoice forcing one; "
        f"stopReason={response.get('stopReason')}"
    )
