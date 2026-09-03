# Week 3 — LangGraph and human-in-the-loop (target: 20 hours)

**Milestone:** submit a 50-question questionnaire. The system drafts every answer, pauses on
the low-confidence ones for human approval, and resumes from where it stopped — even if the
process was killed in between.

**Also this week: start applying for jobs.** You now have enough to talk about.

---

## Why a framework now, and not in week 1

You wrote the loop by hand and it works. So what does LangGraph actually buy?

One thing, mainly: **durable state with interrupts.** A 200-question questionnaire takes
minutes and needs a human to approve some answers. That means the run has to survive being
paused for an hour, or a day, or a crash. Hand-rolling a checkpointer that can serialize
mid-run state, pause on a specific node, and resume correctly is where a raw loop stops
being reasonable.

That's the honest answer, and it's much better than "LangGraph is the standard." Write it in
the ADR that way.

---

## Day 1 — Port the loop (4h)

Move week 1's behaviour into a `StateGraph`. Tools unchanged. Same output.

Define the state explicitly — this is the part worth thinking about:

```python
class QuestionState(TypedDict):
    question: str
    retrieved_chunks: list[Chunk]
    draft_answer: str | None
    citations: list[Citation]
    control_id: str | None
    confidence: Literal["high", "medium", "low"] | None
    critique: str | None          # from the verifier
    revision_count: int           # bound the reflection loop
    status: Literal["drafting", "needs_review", "approved", "rejected"]
```

**Question to answer before you write code:** what's the minimum each node needs to read and
write? State that's too fat makes the graph impossible to reason about; too thin and nodes
start reaching for globals.

Run the week 2 eval set against the ported version. Metrics should match. If they don't,
you changed behaviour by accident — find out where.

## Day 2 — The graph topology (5h)

```
                    ┌──────────────┐
      question ────▶│  supervisor  │
                    └──────┬───────┘
                           ▼
                    ┌──────────────┐
                    │  retriever   │   hybrid search from week 2
                    └──────┬───────┘
                           ▼
                    ┌──────────────┐
                    │   drafter    │   writes answer + control mapping
                    └──────┬───────┘
                           ▼
                    ┌──────────────┐
                    │   verifier   │   is every claim in the answer
                    └──────┬───────┘   actually in the retrieved text?
                           │
              ┌────────────┼────────────┐
       critique│           │ok          │low confidence
              ▼            ▼            ▼
         (back to      ┌────────┐  ┌──────────┐
          drafter)     │ approve│  │  HUMAN   │◀── interrupt()
        max 2 retries  └────────┘  │  REVIEW  │
                                   └──────────┘
```

The **verifier** is the most valuable node and the one to spend time on. Its job: take the
draft answer and the retrieved chunks, and check that every factual claim appears in the
source. If not, send it back with a critique. This is the reflection pattern, and in a
compliance product it's the difference between a toy and something an auditor accepts.

Bound the reflection loop with `revision_count`. An unbounded critique-redraft cycle is the
same runaway failure you triggered in week 1, one level up.

## Day 3 — Checkpointing and interrupt (5h)

- Add a checkpointer (start with SQLite; Postgres is a week 6 concern)
- `interrupt()` before the human review node
- A CLI to list pending reviews, show the draft with its citations, approve or edit
- Resume the graph after approval

**The test that matters:** start a 20-question run, `kill -9` the process halfway, restart,
resume. It should pick up exactly where it stopped and not redo completed work. If it
redoes work, your state boundaries are wrong.

**Also:** log the cost. Re-running work you already paid for is the most expensive kind of
bug in an LLM system.

## Day 4 — Batch mode (4h)

One question is a demo. A questionnaire is a product.

- Ingest a spreadsheet of 50 questions
- Process with bounded concurrency (start at 3-5 parallel; you will hit Bedrock throttling)
- Aggregate: how many auto-answered, how many need review, total cost, wall-clock time
- Export answers back to the original spreadsheet format

**Concurrency will bite you.** Bedrock throttles, and your adaptive retry config from week 1
will start earning its keep. Log what you see.

The aggregate number is your demo headline: *"47 of 50 auto-answered with citations, 3
flagged for review, 4 minutes, $0.11."* That sentence sells the product.

## Day 5 — Confidence scoring and write-up (2h)

Confidence drives the routing, so it has to mean something. Combine:

- retrieval score of the top chunk
- whether the verifier passed on the first attempt
- whether the control mapping was confirmed by lookup
- the model's own stated confidence (least trustworthy — models are overconfident)

Calibrate against your eval set: of the answers marked "high", how many were actually
correct? If that's below ~90%, your threshold is wrong. **Calibration is a great interview
topic** and almost nobody does it.

Write ADRs. Update the README status table.

---

## Break it on purpose

- **Remove the `revision_count` bound.** Watch drafter and verifier argue forever. Same
  runaway lesson as week 1, now between agents.
- **Make the verifier too strict.** Every answer gets sent back; nothing ever completes.
  Shows why "just add a validation agent" isn't free.
- **Crash mid-run without a checkpointer**, then with one. This is the whole justification
  for the framework, demonstrated.
- **Run 20 questions at concurrency 20.** Get throttled. See what your retry config does.
- **Give the drafter chunks from the wrong document.** Does the verifier catch it? That's
  its entire reason for existing.

---

## Definition of done

- [ ] LangGraph version passes the week 2 eval set at parity or better
- [ ] Kill and resume works, verified, no repeated work
- [ ] 50-question batch run with an aggregate report
- [ ] Human review CLI: list, inspect, approve, edit, reject
- [ ] Confidence calibration numbers recorded
- [ ] Reflection loop bounded
- [ ] 3 new ADRs (framework choice, topology, checkpointer)
- [ ] **First job applications sent**

## If you fall behind

Cut batch mode to day 4 of week 4. Keep the interrupt and checkpointing — that's the part
that justifies the framework and it's the best demo moment you'll have.

## Interview answers you'll own after this week

- "When do you actually need an agent framework instead of a loop?"
- "How do you stop two agents from arguing forever?"
- "How does a human get into the loop without blocking everything?"
- "Your system says it's 90% confident — how do you know that number means anything?"
