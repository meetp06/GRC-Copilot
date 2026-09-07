# ADR-0012: Dagster for the ingestion pipeline, oversized on purpose

**Status:** Accepted
**Date:** 2026-09-07

## Context

Week 4 turns a folder of PDFs into a vector index through four steps: read the
files, parse them, write markdown, embed it. That is a shell script.

The question was not whether the pipeline needed an orchestrator — it does not —
but whether adopting one now is worth its cost, given that ingestion in this product
eventually means many customers' document sets, arriving repeatedly, partially failing, and
needing to be re-run for one customer without touching the others.

## Decision

Model ingestion as Dagster assets: `raw_documents → parsed_documents →
policy_markdown → vector_index`, with `document_catalog` branching off
`parsed_documents`.

An asset is a named thing that exists after a computation, rather than a task that runs.
`vector_index` is a thing the system has; Dagster knows what it was built from.

## Alternatives considered

### A shell script or a Makefile

- **Why it's attractive:** zero dependencies, and the pipeline genuinely is four steps.
- **Why I did not pick it here:** it has no vocabulary for partial failure. Two of five
  documents were rejected in the first real run, and "the script exited 0 having silently
  dropped 40% of the input" is exactly the failure this product cannot afford.
- **When it would be the better call:** honestly, today. See the consequences below.

### Prefect

- **Why it's attractive:** lighter than Dagster, and the same task-graph idea.
- **Why I did not pick it here:** it models *runs*, not assets. The question I want to ask is
  "what is the index built from and is it current", which is an asset question.
- **When it would be the better call:** when the work is genuinely tasks — a nightly job, a
  webhook handler — rather than data that exists.

### Step Functions

- **Why it's attractive:** already in AWS, no server, pay per transition.
- **Why I did not pick it here:** the workflow would live in JSON outside the Python, and
  local iteration would mean deploying to test.
- **When it would be the better call:** week 6, if ingestion becomes a deployed service.

## Consequences

**Good:** the asset metadata is the part that earns its keep and would be worth keeping under
any orchestrator. Each run records how many documents were rejected and why, which method
recovered the headings, and the cost of the embedding step. That turns "the pipeline ran"
into "5 documents in, 3 usable, 2 rejected, here is the reason for each", attached to the
asset rather than buried in a log.

`document_catalog` and `policy_markdown` ran in parallel without being asked to, because
both depend only on `parsed_documents`.

**Bad:** 43 packages, including SQLAlchemy, gRPC, GraphQL and a uvicorn web server, to
orchestrate four steps over three documents that complete in about thirty seconds. That is
the honest description. The dependency count is now 43 + 38 (LangGraph) + 9, and this project
began at 9.

**A claim I made and had to retract:** I documented that Dagster would skip the embedding
step when nothing upstream had changed. It does not. `asset materialize --select` runs what
you select; re-running with nothing changed re-embedded the corpus and paid for it again.
Staleness is tracked and shown in the lineage view, but acting on it needs an
`AutomationCondition` this pipeline does not have. MISTAKES.md entry 30, and it is the most
useful thing in this ADR: I wrote the justification for the dependency before testing the
justification.

## Was it worth it

Not on today's numbers, and the ADR should say so rather than construct a defence. Three
documents and four steps do not need this.

It is worth it on two grounds that are about the future rather than the present. First,
ingestion is the part of this product that will actually get complicated — many customers,
repeated arrivals, partial failures, one customer re-run without touching the others — and
that is asset-shaped work. Second, this is a portfolio project, and the cost of learning an
orchestrator on a pipeline small enough to understand completely is much lower than learning
it on one that is not.

The trade is stated rather than hidden: the pipeline could be a shell script today, and the
43 packages buy experience and metadata rather than a capability the current pipeline lacks.

## The interview answer

"Dagster is oversized for what it does here — four steps, three documents, thirty seconds —
and I wrote that in the ADR rather than pretending otherwise. What it actually bought me was
metadata: every run records that two of five documents were rejected and why, attached to the
asset instead of a log line. I also documented a benefit it doesn't have — I claimed it would
skip the embedding step when nothing changed, and it doesn't; that needs an automation
condition. I found that by testing the claim after I'd written it down, which is the wrong
order."
