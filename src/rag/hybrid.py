"""Hybrid retrieval: run vector search and BM25, then fuse the two rankings.

The problem with combining them is that the two scores are not comparable.
Cosine similarity runs -1 to 1 and our real answers score around 0.3. BM25 is
unbounded and can hand back 8.0. Adding them lets BM25 drown the vector signal;
rescaling them needs a normalisation that shifts every time the corpus changes.

Reciprocal Rank Fusion sidesteps that by throwing the scores away and keeping
only the positions:

    fused(chunk) = sum over retrievers of 1 / (k + rank)

A chunk ranked 1st contributes 1/61, ranked 2nd contributes 1/62, and so on with
k = 60. Nothing about the two scales matters -- only that each retriever put the
chunk near the top. A chunk both retrievers like beats a chunk one of them loves.

k = 60 is the value from the original RRF paper. Larger k flattens the
difference between rank 1 and rank 10; smaller k makes first place dominate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.rag.bm25 import BM25
from src.rag.embeddings import embed_query
from src.rag.index import VectorIndex

RRF_K = 60


@dataclass(frozen=True)
class FusedHit:
    score: float  # RRF score, not comparable to cosine
    source: str
    section: str
    vector_rank: int | None
    keyword_rank: int | None


class HybridRetriever:
    """Vector search and BM25 over the same chunks, fused by rank."""

    def __init__(self, index: VectorIndex) -> None:
        self.index = index
        self.bm25 = BM25([c["text"] for c in index.chunks])

    def _vector_ranking(self, query: str, depth: int) -> list[int]:
        """Chunk positions ordered by cosine similarity, best first."""
        query_vector = embed_query(query)
        scores = self.index.vectors @ query_vector
        return [int(i) for i in np.argsort(-scores)[:depth]]

    def search(self, query: str, top_k: int = 5, depth: int = 20) -> list[FusedHit]:
        """Fuse the top `depth` from each retriever, return the best `top_k`.

        `depth` is deliberately larger than `top_k`: a chunk sitting at rank 12
        in both lists is a better answer than one sitting at rank 3 in only one,
        and fusing only the top 5 of each would never see it.
        """
        vector_ids = self._vector_ranking(query, depth)
        keyword_ids = [i for i, _ in self.bm25.top_k(query, k=depth)]

        vector_rank = {cid: r for r, cid in enumerate(vector_ids, start=1)}
        keyword_rank = {cid: r for r, cid in enumerate(keyword_ids, start=1)}

        fused: dict[int, float] = {}
        for ranking in (vector_rank, keyword_rank):
            for cid, rank in ranking.items():
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank)

        best = sorted(fused.items(), key=lambda p: -p[1])[:top_k]
        return [
            FusedHit(
                score=score,
                source=self.index.chunks[cid]["source"],
                section=self.index.chunks[cid]["sections"][0],
                vector_rank=vector_rank.get(cid),
                keyword_rank=keyword_rank.get(cid),
            )
            for cid, score in best
        ]
