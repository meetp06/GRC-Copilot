# ADR-0007: Hybrid BM25 + vector retrieval, tried and rejected

**Status:** Proposed
**Date:** 2026-09-04

<!--
SCAFFOLD. Evidence is real and measured. Prose is yours.
Delete every HTML comment when you're done.
Reproduce with: python -m src.rag.evaluate_retrieval

This is the most valuable ADR of the week. A rejection with numbers is more
credible than a stack of techniques that all supposedly helped. Do not soften it.
-->

## Context

<!--
TODO — 3-5 sentences covering:
  - dense embeddings compress meaning and are weak on exact strings
  - this domain is full of exact strings: SC-28, AES-256, TLS 1.2, CloudTrail
  - the specific observation that motivated trying it: a bare "SC-28" scores
    0.110 against the index, and fifth place scores 0.084 — the right answer
    wins by nothing
-->

## Decision

<!-- TODO — state the rejection plainly, and say the code was kept rather than deleted. Say why. -->

## The measurement

Top-5 over the 40 answerable golden-set questions:

| Config | easy | medium | hard | exact | ALL recall | MRR |
|---|---|---|---|---|---|---|
| Vector only | 100% | 100% | 92% | 90% | **97%** | 0.93 |
| Blind RRF fusion | 100% | 73% | 77% | 100% | 84% | 0.76 |
| Routed on literal tokens | 100% | 93% | 88% | 100% | 95% | 0.90 |

Fusion weight sweep (weight on the BM25 ranking, RRF k=60):

| w_keyword | 0.0 | 0.2 | 0.3 | 0.5 | 0.7 | 1.0 |
|---|---|---|---|---|---|---|
| ALL recall | **98%** | 90% | 84% | 84% | 84% | 82% |

Monotonic. No weight rescues it.

## Alternatives considered

### Blind RRF fusion (both retrievers, every query)

- Why it's attractive: <!-- TODO -->
- Why I did **not** pick it here: <!-- TODO — there are only five slots; vector already fills them correctly 97% of the time, so every slot BM25 wins displaces a correct answer -->
- **When it would be the better call:** <!-- TODO -->

### Routing: use BM25 only when the query contains a literal identifier

- Why it's attractive: <!-- TODO -->
- Why I did **not** pick it here: <!-- TODO — 95%, still under pure vector. The rule fires on "how do you keep API keys out of your codebase", which contains an all-caps token but is a semantic question. -->
- **When it would be the better call:** <!-- TODO -->

### Routing on document frequency instead of a pattern

- Why it's attractive: <!-- TODO — data-driven, no hand-written regex -->
- Why I did **not** pick it here: <!-- TODO — at 58 chunks of ~80 tokens, even "do" and "what" have df <= 2. The corpus is too small for rarity to mean anything. This is worth writing down; it is a real limit of IDF at small scale. -->
- **When it would be the better call:** <!-- TODO -->

## Why RRF specifically failed here

<!--
TODO — this is the part an interviewer will push on. The argument:
RRF discards the scores and keeps only the ranks. Vector search KNEW it was
unsure about "SC-28" (0.110) and confident about remediation (0.740). BM25
knows when it matched nothing at all. Fusion throws all of that away and
treats "BM25's best of a bad list" the same as "BM25's confident exact match".
Write it in your own words.
-->

## Consequences

**Good:** <!-- TODO -->

**Bad:** <!-- TODO — you are shipping a retriever with a known weakness on exact tokens. Say what that costs. -->

## Two caveats that keep this honest

<!--
TODO — write these out. They are what stop this being an overclaim:

1. The exact band is 5 questions. 90% vs 100% is a single gold chunk.
2. Vector recall is 97% largely because 58 chunks is a tiny corpus. On a real
   corpus, dense recall drops and exact matching matters much more. This result
   is expected to REVERSE at week 4 scale.

Then say what you will do about it: the code is tested and kept, and the
comparison gets re-run when the corpus is real.
-->

## The interview answer

<!-- TODO — one sentence. "I tried hybrid search and it made things worse, and here is why" is a stronger answer than most candidates will have. -->
