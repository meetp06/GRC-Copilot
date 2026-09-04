"""Build and search a local vector index over the policy corpus.

No database. The index is two files on disk: a numpy array of vectors and a JSON
file of the chunks they came from. At 58 chunks that is the right answer -- a
vector database here would be infrastructure with nothing to do. Week 4 moves
this to S3 Vectors or pgvector when the corpus is real, and that migration is
worth an ADR of its own.

    python -m src.rag.index build     # embeds the corpus, costs ~$0.0001
    python -m src.rag.index search "how fast do you fix critical bugs"
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.rag.chunking import chunk_corpus
from src.rag.embeddings import embed_query, embed_texts

INDEX_DIR = Path(__file__).resolve().parents[2] / "data" / "index"
DEFAULT_STRATEGY = "section"


@dataclass(frozen=True)
class Hit:
    score: float
    source: str
    section: str
    text: str


class VectorIndex:
    """Chunks plus their vectors, searched by dot product.

    Vectors from Titan are normalised to length 1, so the dot product of a query
    vector and a chunk vector *is* their cosine similarity: 1.0 means identical
    direction, 0.0 means unrelated.
    """

    def __init__(self, vectors: np.ndarray, chunks: list[dict]) -> None:
        self.vectors = vectors
        self.chunks = chunks

    def search(self, query: str, top_k: int = 5) -> list[Hit]:
        query_vector = embed_query(query)
        scores = self.vectors @ query_vector
        best = np.argsort(-scores)[:top_k]
        return [
            Hit(
                score=float(scores[i]),
                source=self.chunks[i]["source"],
                section=self.chunks[i]["sections"][0],
                text=self.chunks[i]["text"],
            )
            for i in best
        ]

    def save(self, strategy: str) -> None:
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        np.save(INDEX_DIR / f"{strategy}.npy", self.vectors)
        (INDEX_DIR / f"{strategy}.json").write_text(
            json.dumps(self.chunks, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, strategy: str = DEFAULT_STRATEGY) -> VectorIndex:
        vectors_path = INDEX_DIR / f"{strategy}.npy"
        if not vectors_path.exists():
            raise FileNotFoundError(
                f"no index for '{strategy}'. Run: python -m src.rag.index build"
            )
        chunks = json.loads(
            (INDEX_DIR / f"{strategy}.json").read_text(encoding="utf-8")
        )
        return cls(np.load(vectors_path), chunks)


def build(strategy: str = DEFAULT_STRATEGY) -> VectorIndex:
    chunks = chunk_corpus(strategy)
    result = embed_texts([c.text for c in chunks])

    print(f"strategy      {strategy}")
    print(f"chunks        {len(chunks)}")
    print(f"dimensions    {result.vectors.shape[1]}")
    print(f"input tokens  {result.input_tokens}")
    print(f"cost          ${result.usd_cost:.6f}")

    index = VectorIndex(
        vectors=result.vectors,
        chunks=[
            {
                "source": c.source,
                "sections": list(c.sections),
                "text": c.text,
            }
            for c in chunks
        ],
    )
    index.save(strategy)
    print(f"saved         {INDEX_DIR}/{strategy}.npy")
    return index


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"build", "search"}:
        print(__doc__)
        raise SystemExit(1)

    if sys.argv[1] == "build":
        build(sys.argv[2] if len(sys.argv) > 2 else DEFAULT_STRATEGY)
        return

    query = " ".join(sys.argv[2:])
    for hit in VectorIndex.load().search(query):
        print(f"{hit.score:.3f}  {hit.source} :: {hit.section}")


if __name__ == "__main__":
    main()
