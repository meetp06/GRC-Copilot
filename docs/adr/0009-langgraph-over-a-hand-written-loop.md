# ADR-0009: LangGraph, adopted for durable state rather than for structure

**Status:** Accepted
**Date:** 2026-09-04

## Context

Week 1 deliberately built the agent loop by hand — a `while` loop that sends
messages and tools to Bedrock, executes whatever tool the model asks for, appends the
result, and repeats. ADR-0003 argued for doing that first. It worked, it was about 220 lines,
and nothing about it was painful.

So the question this week was not "should I use a framework" but "what does one actually buy
me that I do not already have". A framework adopted because it is standard is a dependency
with no stated job, and it cannot be defended when someone asks why it is there.

The forcing requirement came from the product, not the code. A security questionnaire is
200 questions. Some answers are confident enough to send; some need a human to approve them.
That human might respond in an hour, or on Monday. The run has to survive that wait — and
survive the process being killed during it.

## Decision

Adopt LangGraph 1.2.11 with `langgraph-checkpoint-sqlite`, for one reason: **durable state
with interrupts.** Each question is a `StateGraph` run with its own thread id, checkpointed
to SQLite after every node.

Nothing else about the framework was the reason. The nodes-and-edges structure is pleasant
and the hand-written loop could have kept that shape without it.

## Alternatives considered

### Keep the hand-written loop and add checkpointing to it

- **What it is:** serialise the loop's state to SQLite after each step, and add a way to stop
  before human review and resume from a stored position.
- **Why it's attractive:** no dependency, and I would understand every line — which matters
  more in this project than in most.
- **Why I did not pick it here:** this is where a raw loop stops being reasonable. Resuming
  correctly means knowing which step was in flight, replaying nothing that already completed,
  and keeping the serialised shape in step with the code as the graph grows nodes. That is a
  week of work to get right, and the failure mode is silent — a resume that quietly re-runs a
  paid step, or drops one. LangGraph's version is tested by people who have hit those cases.
- **When it would be the better call:** if the run never needed to pause. A pipeline that
  starts and finishes in one process does not need any of this, and the loop was fine for
  exactly that.

### LangChain's AgentExecutor

- **Why it's attractive:** the obvious sibling, and already in the dependency tree.
- **Why I did not pick it here:** it is built around a single agent looping over tools. The
  thing being modelled here is a pipeline with a reflection cycle and a stop-for-a-human
  point, which is a graph, not a loop. And it has no checkpointing story, which is the whole
  reason for adopting anything.
- **When it would be the better call:** a straightforward tool-using agent with no human in
  the middle.

### A durable execution engine — Temporal, Step Functions

- **Why it's attractive:** this problem (long-running work that pauses for a human and must
  survive a crash) is exactly what they are built for, and they are far more rigorous about
  it than a checkpointer in a Python library.
- **Why I did not pick it here:** both mean infrastructure running before week 6, which the
  cost rules rule out — Temporal needs a server, Step Functions needs the workflow modelled
  outside the code. And neither knows anything about LLM state, so I would still be writing
  the graph.
- **When it would be the better call:** when runs must survive across deploys and machines,
  or when the workflow has to be operated by people who are not reading the Python.

## Consequences

**Good:** the thing the framework was adopted for works, and was demonstrated rather than
assumed. A process answered three questions, killed itself with `SIGKILL`, and a second
process read the state back: two finished, one parked at `('human_review',)` with 1173 input
tokens spent. Resuming it in that second process left the token count at 1173 — nothing
re-ran. That single unchanged number is the entire justification for the dependency.

One thread per question also fell out for free, and it matters more than expected: a
50-question batch is 50 independently resumable runs, so a question waiting on a human does
not block the other 49, and a crash at question 40 does not restart questions 1 to 39.

**Bad:** 38 packages, against 9 before. The one that needed attention is `langsmith`, which
ships with LangGraph and sends full prompts and responses to LangChain's cloud when tracing
is enabled. This product's prompts contain customer policy text by design, so
`LANGCHAIN_TRACING_V2` and `LANGSMITH_TRACING` are pinned false in `.env.example` with the
reason written next to them. That is one environment variable away from being a data
incident, and it is a cost of the dependency, not a footnote.

Beyond that: `langchain-core` moves quickly and this pins an early 1.x; state now has to stay
serialisable, which is a real constraint on future nodes; and I own less of the machinery I
can explain from memory.

## What the framework did not buy

Worth naming, because the honest version of this ADR is narrow. Days 1 and 2 — porting the
loop, adding a verifier, bounding the reflection cycle — could all have stayed hand-written.
The port was deliberately shipped as a straight line (`retrieve → draft → END`) and re-run
against the week 2 eval set, and every metric came back identical, which is precisely the
point: the framework changed nothing about behaviour.

Day 3 is where it earned its place. If this project never needed a human in the middle, the
right call would have been to keep the loop.

## The interview answer

"I wrote the loop by hand first, so I could answer this properly. LangGraph bought me exactly
one thing: durable state with interrupts. A questionnaire pauses for a human approval that
might come back on Monday, and the run has to survive that. I proved it — killed the process
with SIGKILL mid-run, resumed in a new process, and the token count was identical, so nothing
I'd already paid for was re-run. Everything else it gives me I already had."
