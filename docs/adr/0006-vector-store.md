# ADR-0006: A local numpy file instead of a vector database

**Status:** Proposed
**Date:** 2026-09-04

<!--
SCAFFOLD. Evidence is real and measured. Prose is yours.
Delete every HTML comment when you're done.
Reproduce with: python -m src.rag.index build
-->

## Context

<!--
TODO — 3-5 sentences covering:
  - what has to be stored: 58 chunks x 1024 float32 = about 240 KB
  - what has to be supported: one similarity search per question
  - the hard cost constraint from docs/COST-GUARDRAILS.md
Say plainly how small this problem currently is. That is the whole argument.
-->

Current index: 58 chunks, 1024 dimensions, built for $0.000075. Search is one matrix
multiply — the vectors are unit length, so cosine similarity is a plain dot product
(`scores = V @ q`).

## Decision

<!-- TODO — name the files and where they live. -->

## Alternatives considered

### OpenSearch Serverless

- What it is: <!-- TODO -->
- Why it's attractive: <!-- TODO -->
- Why I did **not** pick it here: <!-- TODO — roughly $350/month idle; would consume the $100 credit in about 9 days; explicitly banned in CLAUDE.md -->
- **When it would be the better call:** <!-- TODO -->

### pgvector on RDS

- What it is: <!-- TODO -->
- Why it's attractive: <!-- TODO -->
- Why I did **not** pick it here: <!-- TODO -->
- **When it would be the better call:** <!-- TODO — this is the likely week 4 answer; say what would trigger it -->

### S3 Vectors

- What it is: <!-- TODO -->
- Why it's attractive: <!-- TODO -->
- Why I did **not** pick it here: <!-- TODO -->
- **When it would be the better call:** <!-- TODO -->

### FAISS

- What it is: <!-- TODO -->
- Why it's attractive: <!-- TODO -->
- Why I did **not** pick it here: <!-- TODO — a dependency that buys an index structure; at 58 vectors a brute-force scan is already sub-millisecond -->
- **When it would be the better call:** <!-- TODO — roughly what corpus size makes an ANN index worth it? -->

## Consequences

**Good:** <!-- TODO -->

**Bad:** <!-- TODO — you are committing to a migration in week 4. Say so, and say what makes that migration cheap or expensive. -->

## What would flip this decision

<!--
TODO — be specific. Name the thresholds, not vibes. Some candidates:
  - corpus size at which a linear scan stops being instant
  - needing more than one process to read the index
  - needing metadata filters (by document, by date, by customer)
  - needing the index to survive without a rebuild
-->

## Note

`data/index/` is gitignored: it is derived data, rebuildable in seconds for $0.000075.
The embedding model is a hard dependency of the index — a query embedded by a different
model, or at different dimensions, lands in a different space and returns noise with no
error. Any model change means a full rebuild.

## The interview answer

<!-- TODO — one sentence. The strongest version of this answer is about *not* building infrastructure. -->
