# ADR-0006: A local numpy file instead of a vector database

**Status:** Accepted
**Date:** 2026-09-04

## Context

Week 2 introduced embeddings, which means the project now has vectors to store and search.
The instinct at this point is to reach for a vector database, because that is what every RAG
architecture diagram shows.

It is worth stating how small this problem actually is before choosing anything. The index
is 58 chunks at 1024 dimensions in float32 — about 240 KB, comfortably smaller than a phone
photo. Building it embedded 3,770 tokens and cost $0.000075. The only operation required is
one similarity search per question, and because Titan returns unit-length vectors, that
search is a single dot product against a 58-row matrix (`scores = V @ q`). It completes in
under a millisecond.

Against that sits a hard constraint from `docs/COST-GUARDRAILS.md`: total spend under
$5/month, and no always-on compute before week 6.

## Decision

Store the index as two files on local disk: `data/index/section.npy` for the vectors and
`data/index/section.json` for the chunk text and metadata. Search is a numpy matrix multiply
in `src/rag/index.py`. No database, no service, no container.

## Alternatives considered

### OpenSearch Serverless

- **What it is:** AWS's managed search service with vector support, the option most AWS RAG
  tutorials and reference architectures use.
- **Why it's attractive:** hybrid search, filtering, and scale all built in, fully managed,
  and it is the path of least resistance if you follow AWS's own documentation.
- **Why I did not pick it here:** it bills roughly $350/month for minimum capacity whether
  or not anything queries it. That is not a rounding error against a $5/month target — it
  would consume the entire $100 credit in about nine days while sitting idle. It is banned
  outright in `CLAUDE.md` for that reason.
- **When it would be the better call:** a funded production system with real query volume
  and a corpus large enough that the managed capacity is actually used.

### pgvector on RDS

- **What it is:** a PostgreSQL extension adding a vector column type and similarity
  operators, so vectors live in an ordinary relational database.
- **Why it's attractive:** it puts vectors next to the relational data this product will
  need anyway — questionnaires, questions, answers, reviewers, approval state. One database
  and one transaction boundary instead of two systems kept in sync. Metadata filtering is
  just a `WHERE` clause.
- **Why I did not pick it here:** the smallest sensible instance still bills continuously,
  and there is no relational data yet to justify it. Right now it would be a database
  holding one table nobody joins against.
- **When it would be the better call:** this is the likely week 4 or 5 answer. The trigger
  is the moment the product needs to store *state* rather than just search — a questionnaire
  in progress, answers pending human review — because at that point the database exists
  regardless and putting vectors in it is nearly free.

### S3 Vectors

- **What it is:** vector storage and search built into S3, billed per request and per GB
  stored rather than per provisioned hour.
- **Why it's attractive:** no idle cost, which is exactly the constraint that rules out the
  other managed options. It fits the "Lambda and S3 only" rule for weeks 1 to 5.
- **Why I did not pick it here:** it is still a network call and an API to integrate against,
  in exchange for solving a problem I do not have. 240 KB does not need to leave the laptop.
- **When it would be the better call:** when the index outgrows what should sit in a Lambda
  deployment package, but the query volume is still too low to justify anything provisioned.
  That is the natural next step after local files.

### FAISS

- **What it is:** Meta's library for approximate nearest-neighbour search over large vector
  sets.
- **Why it's attractive:** the standard local answer, fast, and no service to run.
- **Why I did not pick it here:** it is a dependency whose entire value is an index structure
  that makes search sublinear. At 58 vectors a brute-force scan is already sub-millisecond,
  so the index structure would be pure overhead — and approximate search trades exactness
  for a speed I do not need.
- **When it would be the better call:** somewhere in the tens of thousands of vectors, when
  a linear scan stops being instant. Below roughly 10,000 vectors, numpy is not the slow
  option; it is the simple one.

## Consequences

**Good:** zero cost at rest, zero setup, and the whole thing rebuilds in seconds. Iteration
is fast enough that I re-embedded the corpus several times during week 2 without thinking
about it. There is no schema, no migration, and no service that can be down. Most usefully
for the eval work, the retriever is a pure function of two files, so a run is exactly
reproducible.

**Bad:** I am committing to a migration. Search, storage, and metadata filtering are all
tangled into one class today, so when the store changes, `VectorIndex` changes with it. The
index also lives on one laptop: it is not shared between processes, not backed up, and not
reachable from a Lambda. And a linear scan is O(n) — fine at 58, unacceptable at 500,000,
with no warning in between except a growing latency number nobody is watching.

## What would flip this decision

Specific thresholds rather than vibes:

- **Corpus size** — roughly 10,000 chunks, where a full scan per query stops being instant.
- **More than one reader** — the moment an API process needs the index, a file on my laptop
  stops being a store and becomes a deployment problem.
- **Metadata filters** — "search only this customer's policies", or "only documents reviewed
  in the last year". Expressing that over a numpy array means writing a query engine, which
  is the point at which I should be using one instead.
- **State, not just search** — once questionnaires and human review live in a database, the
  argument for keeping vectors outside it disappears.

## Note

`data/index/` is gitignored: it is derived data, rebuildable with
`python -m src.rag.index build` in seconds for $0.000075. Committing it would be committing
a build artefact.

The embedding model is a hard dependency of the index. A query embedded by a different
model, or at different dimensions, lands in a different space and returns noise — with no
error, no warning, just quietly wrong answers. Any change to the embedding model or its
dimension count requires a full rebuild, and that is a good reason to keep rebuilds cheap.

## The interview answer

"I didn't build the infrastructure. It's 58 chunks and 240 KB — that's a numpy array, not a
database. I wrote down what would change my mind: about ten thousand chunks, a second
process needing the index, or metadata filtering. Starting local means migrating later, and
I'd rather do that migration knowing what I actually need than provision OpenSearch at $350
a month to serve a file smaller than a photo."
