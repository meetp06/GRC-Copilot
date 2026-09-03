"""Turn text into vectors using Amazon Titan Text Embeddings V2 on Bedrock.

A vector is just a list of numbers that stands for the meaning of a piece of
text. Two texts that mean similar things get similar numbers, even when they
share no words. That is the whole reason this file exists: week 1 keyword search
missed 8 of 12 paraphrased questions because 'remediate' and 'fix' are different
strings.

We ask Titan for normalised vectors (every vector scaled to length 1). That makes
cosine similarity -- the usual 'how close in meaning are these?' measure -- equal
to a plain dot product, so search is one matrix multiply.

Cost: Titan V2 is $0.02 per million input tokens. The whole policy corpus is
roughly 6,000 tokens, so building the index costs about $0.0001.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import boto3
import numpy as np

DEFAULT_MODEL_ID = "amazon.titan-embed-text-v2:0"

# Titan V2 can return 256, 512 or 1024 numbers per text. Fewer numbers means a
# smaller index and faster search, but less of the meaning survives. 1024 is the
# default; shrinking it is a measurable trade-off, not an obvious win.
DEFAULT_DIMENSIONS = 1024


@dataclass(frozen=True)
class EmbedResult:
    """Vectors plus what they cost, so spend is never a guess."""

    vectors: np.ndarray  # shape (n_texts, dimensions), float32
    input_tokens: int

    @property
    def usd_cost(self) -> float:
        return self.input_tokens * 0.02 / 1_000_000


def _client():
    return boto3.client(
        "bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1")
    )


def embed_texts(
    texts: list[str],
    *,
    model_id: str | None = None,
    dimensions: int = DEFAULT_DIMENSIONS,
) -> EmbedResult:
    """Embed a list of texts, one Bedrock call each.

    Titan has no batch endpoint, so this is a loop. At 58 chunks that is fine.
    When the corpus is real (week 4) this becomes the reason to move embedding
    into a pipeline rather than a request path.
    """
    model_id = model_id or os.environ.get("BEDROCK_EMBED_MODEL_ID", DEFAULT_MODEL_ID)
    client = _client()

    vectors: list[list[float]] = []
    total_tokens = 0

    for text in texts:
        body = json.dumps(
            {"inputText": text, "dimensions": dimensions, "normalize": True}
        )
        response = client.invoke_model(modelId=model_id, body=body)
        payload = json.loads(response["body"].read())
        vectors.append(payload["embedding"])
        total_tokens += payload.get("inputTextTokenCount", 0)

    return EmbedResult(
        vectors=np.array(vectors, dtype=np.float32),
        input_tokens=total_tokens,
    )


def embed_query(text: str, **kwargs) -> np.ndarray:
    """Embed a single question. Returns a 1-D vector.

    The query must be embedded by the same model, at the same dimensions, as the
    documents. Mixing models produces numbers that live in different spaces and
    the search silently returns noise -- no error, just bad answers.
    """
    return embed_texts([text], **kwargs).vectors[0]
