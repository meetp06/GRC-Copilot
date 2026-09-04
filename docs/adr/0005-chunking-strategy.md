# ADR-0005: Section-aware chunking over fixed-size windows

**Status:** Accepted
**Date:** 2026-09-04

## Context

A language model cannot read the whole policy corpus on every question, so the documents
have to be split into smaller pieces before they are indexed. Those pieces are the unit of
retrieval: search returns chunks, and the model only ever sees the chunks it was handed.

That makes the split more consequential than it first looks. If a chunk boundary lands in
the middle of the sentence that answers a question, the answer no longer exists in any
single retrievable unit. No embedding model recovers it, no reranker recovers it, and the
failure shows up later as "retrieval is bad" when the real fault was the knife.

Week 2 needed an index, so the split had to be decided first — and decided on measurement,
because the eval set (`evals/golden_set.yaml`) already names the exact sections that contain
each answer. That turns "which chunking is better" into a countable question.

## Decision

Split on markdown `##` headings, keep each section whole as one chunk, and prepend the
document's title to the chunk text before embedding. Implemented as `chunk_by_section` in
`src/rag/chunking.py`; the index built from it is the one that ships.

## Alternatives considered

Measured on the real corpus (12 documents, 58 sections) against the 34 distinct gold
sections named by the golden set. "Gold sections intact" counts gold passages that survive
whole inside a single chunk.

| Strategy | chunks | median tokens | sections/chunk | gold sections intact |
|---|---|---|---|---|
| Section-aware | 58 | 79 | 1.00 | 34/34 |
| Fixed 512/64 | 13 | 395 | 4.54 | 33/34 |
| Fixed 128/16 | 46 | 128 | 2.20 | 17/34 |

### Fixed-size window, 512 tokens / 64 overlap

- **What it is:** slide a 512-token window across the raw document, stepping 448 tokens each
  time so consecutive chunks share 64 tokens of overlap. Headings are ignored entirely.
- **Why it's attractive:** it is the default in nearly every RAG tutorial, it needs no
  assumptions about document structure, and — importantly — **it did not lose on recall**.
  33 of 34 gold sections survived intact. If gold intactness had been the only metric, I
  would have concluded fixed-size was fine.
- **Why I did not pick it here:** it loses on the other axis. A 512-token window is larger
  than most of my policy documents, so 12 documents collapse into 13 chunks averaging 4.54
  sections each. A "chunk" is effectively an entire policy. Retrieve five of them and the
  model has been handed 38% of the corpus — which costs tokens, and buries the relevant
  three sentences among thirty irrelevant ones.
- **When it would be the better call:** unstructured text with no reliable headings —
  meeting transcripts, scraped web pages, OCR'd PDFs, support tickets. When there is no
  author-provided structure to exploit, a fixed window is the honest fallback.

### Fixed-size window, 128 tokens / 16 overlap

- **What it is:** the same sliding window, tuned small enough that it actually cuts inside
  my sections rather than swallowing them whole. I ran this configuration specifically to
  make my preferred answer face a real test.
- **Why it's attractive:** small chunks are high-precision. Each one is tightly on a single
  topic, so a retrieved chunk is mostly signal.
- **Why I did not pick it here:** it destroys half the eval set before retrieval is even
  involved. 17 of 34 gold sections were split across a boundary — including `Encryption at
  rest` and `Remediation timelines`, the two most-asked sections in the corpus. Precision on
  a chunk that no longer contains the answer is worth nothing.
- **When it would be the better call:** a corpus of long documents where an answer is
  reliably one or two sentences, and where a reranker over many small candidates is cheaper
  than feeding a model large ones.

### Contextual retrieval (a generated document summary prepended to every chunk)

- **What it is:** before embedding, ask a model to write a one-line summary of the parent
  document and prepend it to each chunk, so an isolated chunk carries its own context.
- **Why it's attractive:** it fixes the orphaned-chunk problem. "Critical severity findings
  are remediated within 7 days" means little on its own; the same text under "Vulnerability
  Management Policy" is unambiguous.
- **Why I did not pick it here:** I get the cheap 80% of it for free. Section-aware chunking
  already prepends the document title, which is the same idea without a model call per
  chunk. Paying for generated summaries before measuring whether the free version is
  insufficient would be spending on an unproven problem.
- **When it would be the better call:** when document titles are uninformative (`Policy
  v3_FINAL.docx`), or when chunks routinely need context that the title cannot carry —
  effective dates, which business unit a policy applies to.

## Consequences

**Good:** every gold section survives whole, so retrieval failures are now genuinely
retrieval failures rather than chunking damage. Each chunk maps to exactly one section,
which means a citation can name a real heading a human can go and read — that traceability
is the product's core promise, and it falls out of this choice for free. And there are no
parameters to tune: no window size, no overlap, no argument about either.

**Bad:** it assumes the corpus is well-structured markdown with meaningful `##` headings.
Real customer policies arrive as PDFs and Word files with inconsistent heading levels, and
week 4's ingestion pipeline has to produce that structure before this strategy applies —
so I have moved work rather than removed it. Chunk sizes are also uneven (median 79 tokens,
max 226); a section that ran to 5,000 tokens would produce one chunk too large to be useful
and there is currently no cap to catch it.

## Notes on the measurement

The counter-intuitive detail worth keeping: `Control mapping summary` is 226 estimated
tokens and the fixed-512 window is more than twice that size, yet the section still got
split — because the window boundary happened to land inside it. Chunk size is not the
property that matters. Boundary alignment is. "Just make the chunks bigger than your
sections" does not work, because a blind cut lands wherever it lands.

Token counts throughout are `len(text) // 4`, a heuristic rather than a real tokenizer.
Titan's tokenizer is not available locally, and borrowing tiktoken would give a precise
count for the wrong model family. Both strategies are measured with the same estimator, so
the comparison between them holds even though the absolute numbers are approximate.

## The interview answer

"I measured it instead of assuming. Policy documents are already chunked by their authors —
the headings are a human-curated segmentation and it's free — so section-aware kept 34 of 34
gold passages intact while a 128-token window split 17 of them. The finding I didn't expect
was that a 512-token window kept almost everything intact too, and still lost, because at
that size a chunk is a whole document and retrieving five of them returns 38% of the
corpus. Chunking trades recall against precision, and you have to measure both."
