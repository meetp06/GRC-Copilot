# ADR-0011: SQLite checkpointing, one thread per question

**Status:** Accepted
**Date:** 2026-09-04

## Context

A questionnaire takes minutes to draft and then waits on a human. The wait is the problem: a
reviewer might approve an answer in an hour or on Monday, and the run has to survive that,
including the process being killed during it.

Two decisions follow from that, and they are separable: where the state is written, and how
it is keyed.

## Decision

**Where:** `langgraph-checkpoint-sqlite`, writing to `data/runs.sqlite`. Every node's output
is checkpointed as it completes.

**How it is keyed:** one thread id per question, set to the question's own id. A 50-question
questionnaire is 50 independent resumable runs, not one run containing 50 questions.

## Why one thread per question

This is the decision worth defending, because the obvious alternative — one thread for the
whole questionnaire — is simpler to picture.

With one thread for 50 questions:

- Question 7 stops for a human, and questions 8 through 50 wait behind it.
- A crash at question 40 restarts the batch.
- The reviewer's approval has to be routed to the right point inside one large state object.

With 50 threads:

- Question 7 sits paused while the other 49 finish.
- A crash costs only whatever was in flight.
- A reviewer approves question 7 next Monday without touching anything else.
- Re-running the file skips everything already finished, and pays nothing for it.

A questionnaire is not one job. It is 50 jobs that arrived together, and the checkpoint key
should match the unit that can independently stop.

## Alternatives considered

### An in-memory checkpointer

- **Why it's attractive:** zero setup, and enough for tests.
- **Why I did not pick it here:** it dies with the process, which is the exact thing being
  defended against.
- **When it would be the better call:** unit tests, and only there.

### Postgres checkpointer

- **Why it's attractive:** where this goes when more than one machine runs the graph, and the
  natural companion to putting vectors in pgvector (ADR-0006).
- **Why I did not pick it here:** an RDS instance bills continuously, which the cost rules
  rule out before week 6, and there is one machine.
- **When it would be the better call:** the moment a second process needs to read the queue,
  or the API in week 5 needs to serve review state to a browser.

### A separate queue table for pending reviews

- **Why it's attractive:** an explicit list of what needs a human, easy to index and query.
- **Why I did not pick it here:** two sources of truth that can disagree. A question is
  pending precisely because its graph is parked at the interrupt, so the checkpoint database
  already knows. The review CLI reads pending work from the checkpoints and there is nothing
  to keep in sync.
- **When it would be the better call:** when the queue needs fields the graph does not have —
  an assignee, a due date, a priority.

## Consequences

**Good:** demonstrated rather than assumed. A process answered three questions and killed
itself with `SIGKILL`. A second process, with nothing in memory, read back two finished
questions and one parked at `('human_review',)` with 1173 input tokens spent. Resuming it
there left the count at 1173 — retrieve, draft and verify did not re-run.

Re-running a finished question skips the model entirely, which a test asserts by counting
drafter calls across two runs of the same row. Re-paying for work already bought is the most
expensive bug class in an LLM system, and it is now a test rather than an intention.

**Bad:** the checkpoint database is a file on one laptop — not shared, not backed up, not
reachable from a Lambda. It grows without bound: every node of every run is a row, and there
is no retention policy. And it contains customer questionnaire text and retrieved policy
extracts, so it is gitignored, but nothing yet encrypts it at rest. That last point is
uncomfortable in a compliance product and belongs on the week 6 threat model.

## A bug this design caused

The review queue is derived from checkpoints, which means reading them correctly matters.
`_pending()` walked checkpoints newest-first but used a single dict for both deduplication and
results, adding a thread only when its checkpoint matched `needs_review`. A thread whose newest
checkpoint said `rejected` was therefore never marked as seen, and the older `needs_review`
checkpoint right behind it resurfaced — so rejecting a question left it in the queue.

Fixed with a separate `visited` set and a regression test. Logged as MISTAKES.md entry 21. The
general shape: a deduplication structure written only on the branch that keeps a row is not
deduplicating anything.

## The interview answer

"Each question gets its own checkpoint thread, so a 50-question questionnaire is 50
independently resumable runs. One thread for the whole thing would mean question 7 waiting on
a human blocks the other 49, and a crash at question 40 restarts everything. The unit you key
checkpoints by should be the unit that can independently stop — and for a questionnaire that's
the question, not the file."
