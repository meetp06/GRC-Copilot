# ADR-0005: Section-aware chunking over fixed-size windows

**Status:** Proposed
**Date:** 2026-09-04

<!--
SCAFFOLD. The evidence below is real and measured — it is yours to keep.
The prose is yours to write. Delete every HTML comment when you're done.
Reproduce any number here with: python -m src.rag.report_chunks
-->

## Context

<!--
TODO — write 3-5 sentences covering:
  - the model cannot read a whole document, so text must be split before indexing
  - a chunk is the unit that gets retrieved: if the answer spans a boundary,
    no embedding model or reranker can recover it
  - what constraint made this decision necessary now (week 2 needed an index)
Write it for someone who has never seen the repo.
-->

## Decision

<!-- TODO — one or two sentences. Name the strategy and the parameter values. -->

## Alternatives considered

Measured on the real corpus (12 documents, 58 sections) against the 34 distinct gold
sections named by `evals/golden_set.yaml`. "Gold sections intact" counts gold passages that
survive whole inside a single chunk.

| Strategy | chunks | median tokens | sections/chunk | gold sections intact |
|---|---|---|---|---|
| Section-aware | 58 | 79 | 1.00 | 34/34 |
| Fixed 512/64 | 13 | 395 | 4.54 | 33/34 |
| Fixed 128/16 | 46 | 128 | 2.20 | 17/34 |

### Fixed-size window, 512 tokens / 64 overlap

- What it is: <!-- TODO -->
- Why it's attractive: <!-- TODO — it is the tutorial default, and note it did NOT lose on recall (33/34) -->
- Why I did **not** pick it here: <!-- TODO — 4.54 sections per chunk; at top-5 that is 38% of the corpus; precision, not recall, is what it costs -->
- **When it would be the better call:** <!-- TODO -->

### Fixed-size window, 128 tokens / 16 overlap

- What it is: <!-- TODO -->
- Why it's attractive: <!-- TODO -->
- Why I did **not** pick it here: <!-- TODO — 17 of 34 gold sections split, including Encryption at rest and Remediation timelines, the two most-asked sections -->
- **When it would be the better call:** <!-- TODO -->

### Contextual retrieval (a document summary prepended to every chunk before embedding)

- What it is: <!-- TODO -->
- Why it's attractive: <!-- TODO -->
- Why I did **not** pick it here: <!-- TODO — not tried; section-aware already prepends the document title, which is the cheap version of the same idea -->
- **When it would be the better call:** <!-- TODO -->

## Consequences

**Good:** <!-- TODO -->

**Bad:** <!-- TODO — think about: what happens when a policy document has no headings? what if one section is 5,000 tokens? -->

## Notes on the measurement

One detail worth keeping, because it is the counter-intuitive part:
`Control mapping summary` is 226 estimated tokens and the fixed-512 window is more than
twice that size — yet it still got split, because the window boundary landed inside it.
Chunk size is not the property that matters; boundary alignment is.

Token counts throughout are `len(text) // 4`, a heuristic rather than a real tokenizer.
Titan's tokenizer is not available locally, and tiktoken would be precise about the wrong
model family. Both strategies use the same estimator, so the comparison holds.

## The interview answer

<!-- TODO — one sentence you can say out loud. -->
