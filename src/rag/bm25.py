"""BM25 keyword ranking over the chunked corpus. No dependencies, ~40 lines of maths.

Why this exists alongside vector search: embeddings are good at meaning and bad
at exact strings. Searching the index for 'SC-28' scores 0.110 -- the right
section wins, but by 0.026 over fifth place, which is noise. The corpus is full
of tokens that must match literally: SC-28, AES-256, TLS 1.2, CloudTrail.

BM25 scores a chunk on three ideas:

  rare words count more   a term in 1 of 58 chunks is strong evidence;
                          a term in 50 of 58 is worth almost nothing (idf)
  repeats saturate        the 5th occurrence adds far less than the 2nd (k1)
  short chunks win ties   the same match in less text is a denser signal (b)

The first idea is why there is no stopword list here. Week 1 keyword search
needed a hand-written set of {the, a, is, are, ...}; BM25 derives the same
effect from the corpus, and it stays correct when the corpus changes.
"""

from __future__ import annotations

import math
import re
from collections import Counter

# Keep '-' and '.' inside tokens so 'sc-28', 'aes-256' and '1.2' survive intact.
# Splitting those apart is exactly the failure this module exists to prevent.
TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*")

K1 = 1.5  # how fast repeat matches stop helping
B = 0.75  # how strongly to penalise long chunks


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


class BM25:
    """A BM25 index over a fixed list of documents."""

    def __init__(self, documents: list[str]) -> None:
        self.docs = [tokenize(d) for d in documents]
        self.lengths = [len(d) for d in self.docs]
        self.avg_length = sum(self.lengths) / len(self.docs) if self.docs else 0.0
        self.term_freqs = [Counter(d) for d in self.docs]

        doc_freq: Counter[str] = Counter()
        for doc in self.docs:
            doc_freq.update(set(doc))

        n = len(self.docs)
        # Smoothed inverse document frequency. The +1 inside the log keeps this
        # positive even for a term present in every document.
        self.idf = {
            term: math.log(1 + (n - df + 0.5) / (df + 0.5))
            for term, df in doc_freq.items()
        }

    def scores(self, query: str) -> list[float]:
        """Score every document against the query. Higher is better, 0.0 means no overlap."""
        out = [0.0] * len(self.docs)
        for term in tokenize(query):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, freqs in enumerate(self.term_freqs):
                freq = freqs.get(term, 0)
                if not freq:
                    continue
                norm = 1 - B + B * self.lengths[i] / self.avg_length
                out[i] += idf * freq * (K1 + 1) / (freq + K1 * norm)
        return out

    def top_k(self, query: str, k: int = 5) -> list[tuple[int, float]]:
        ranked = sorted(enumerate(self.scores(query)), key=lambda p: -p[1])
        return [(i, s) for i, s in ranked[:k] if s > 0.0]
