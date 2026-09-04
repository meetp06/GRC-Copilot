# ADR-0010: Graph topology — a separate verifier, and a bounded reflection loop

**Status:** Accepted
**Date:** 2026-09-04

## Context

ADR-0008 ended with a hole it could name but not fix. The refusal cascade — the drafter's own
`answerable` flag plus a substring check for refusal language — catches most failures, and
misses the dangerous one:

> Retrieval returns `vendor-management-policy.md`, which says we require a SOC 2 Type II
> report *from our vendors*. The question asks whether we hold one. If the drafter answers
> confidently from that passage, its flag says answerable and its text contains no refusal
> language. Both cheap signals agree, and both are wrong.

At evaluation time the golden set's band label catches that for free. At runtime there is no
label. Something else has to check.

## Decision

```
START → retrieve → draft → verify → finalise → END
                     ↑        │                  ↓
                     └────────┘         needs_review → human_review → END
                  max 2 revisions
```

Five nodes. The verifier is a separate agent with its own prompt and no memory of having
written the draft. The retry edge is the only backward edge in the graph and it is bounded by
a counter in state.

## Why the verifier cannot be the drafter

A drafter asked to re-read its own answer is being asked to find a mistake it did not believe
it was making. The failure mode this exists to catch is one where the drafter was *fooled* —
so the same context that fooled it is the context it would be re-reading.

So the verifier gets a narrower job: not "is this answer good", but "does each claim appear in
the text it cites". It is shown only the passages the draft actually cited, not all five —
otherwise it can justify a claim from a passage the drafter never used, which is how a
citation check quietly stops checking citations.

## The first verifier was useless

Worth recording, because the fix generalises and the failure was invisible without an
adversarial test.

Version one asked for a single boolean: `supported: true/false`. It passed **every** case,
including a draft claiming we hold a SOC 2 Type II report sourced from the vendor passage, and
an invented "keys rotate every 90 days" against a source stating annual rotation. 2 of 4
adversarial cases wrong, in the direction that matters.

Same model, same temperature, and the fix was the schema rather than the prompt:

| | v1 | v2 |
|---|---|---|
| Asks for | one boolean | every claim, separately |
| Evidence | none | the verbatim sentence supporting each claim |
| Subject check | none | whether that sentence is about us |
| Enforcement | trust | `quote_is_real()` confirms the quote occurs in the source |
| Adversarial set | 2/4 | **4/4** |

A boolean is free to agree with. A quote either exists in the text or it does not — and the
Python check is what makes asking for one worth anything, because otherwise a model can invent
a supporting sentence as easily as it can assert `true`.

This is ADR-0008's finding a second time, and a third instance followed the same day: the
exported answers were written in the questioner's voice ("your backups are encrypted"), and
that was fixed by a field description in the tool schema, not by the system prompt. **When a
model behaves wrong, change what the schema requires before rewriting the instructions.**

## Bounding the reflection loop

`revision_count` lives in state, is incremented by the verify node, and is read by the routing
function. No model can see it or change it.

Unbounded, the drafter and verifier rewrite and reject each other until the token budget is
gone — the week 1 runaway failure one level up, between two agents rather than inside one
loop. `MAX_REVISIONS = 2` is a guess rather than a measurement; the 45-question run used 6
revisions total and nothing ever hit the cap, so the bound has not yet been tested by anything
real.

The critique from the verifier is passed back into the retry. Without it the drafter would
redraft identically at temperature 0 and burn its revisions for nothing.

## What the verifier cost

Measured over the 45-question golden set:

| | before | after |
|---|---|---|
| Answerable accuracy | 91% | 87% |
| Citation precision | 97% | 99% |
| Hallucination | 0% | 0% |
| Cost per run | $0.0034 | $0.0069 |

It is not a clear win. Four points of accuracy and double the money, for two points of
citation precision and a guard against fabricated claims that the eval set cannot see.

Six drafts were rejected and all six recovered on retry. Three of those retries came back as
refusals on questions the corpus can answer — the model taking the escape hatch after being
criticised.

I tried removing the escape hatch from the retry prompt. Running it properly — the same config
twice for a noise floor, then the variant — moved two questions in **opposite** directions, so
the change was indistinguishable from noise and was not made. That measurement is what
produced the amendment to ADR-0008, and it is the more valuable finding of the two.

## Consequences

**Good:** the SOC 2 subject-drift case is caught at runtime, where no label exists. Nothing
auto-approves without passing verification — refusal, failed verification, and
out-of-revisions all route to a human, because the safe default in a compliance product is a
queue, not a send.

**Bad:** every answerable question costs two model calls instead of one. Four points of
answerable accuracy went to conservatism. And `MAX_REVISIONS = 2` is untested by real
pressure — nothing has reached it yet, so I do not know whether a third attempt would help or
whether two is already one too many.

**Unresolved:** the "the answer is no" confusion from MISTAKES entry 14 is still present. The
model writes a correct negative answer and flags it unanswerable. The next thing to try is a
schema change, not a prompt change — rename `answerable` to something that cannot be misread
as "is the answer yes", or split it into two required fields. That follows the pattern that has
now worked three times.

## The interview answer

"The verifier is a separate agent because the drafter can't catch the failure that matters —
if retrieval returns a passage about our vendors' SOC 2 reports and the model answers as
though it's ours, the model that was fooled is the wrong thing to ask. My first verifier was
useless: I asked for one boolean and it agreed with everything. I changed the schema to
require a verbatim quote per claim and checked in Python that the quote exists in the source,
and it went from 2 of 4 adversarial cases to 4 of 4. And the loop is bounded by a counter no
model can see, because two agents arguing forever is just the runaway failure one level up."
