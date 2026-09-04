# ADR-0008: Concise prompt over strict, and why the schema does the real work

**Status:** Accepted
**Date:** 2026-09-04

## Context

Week 1 asked the model to return JSON by describing the shape in the prompt, then recovered
it with string surgery: strip the markdown fence, find the outermost braces, slice, parse,
hope. It broke on a correct answer, because Nova Lite prefixed the response with a
`<thinking>` block (MISTAKES.md entry 7).

Week 2 replaced that with a forced tool call. The tool's input schema *is* the answer shape,
so Bedrock rejects anything that does not match it and there is nothing left to parse. That
removed the parsing question entirely.

It left a different one open. With the shape fixed, what should the system prompt say? The
honest answer is that I had no idea, and that "write a careful, thorough prompt" is an
instinct rather than a finding. Since the eval set already existed, this could be measured.

## Decision

Ship the three-sentence `concise` prompt, defined as `SYSTEM_PROMPT` in `src/rag/answer.py`.
`evaluate_answers.py` imports it from there rather than keeping a copy, so the prompt that is
measured and the prompt that ships cannot drift apart.

## The measurement

All 45 golden-set questions, one Nova Lite call each, identical retrieval and identical tool
schema. The only variable was the system prompt.

| Prompt | answerable accuracy | citation precision | answered w/o citing | hallucination | cost |
|---|---|---|---|---|---|
| naive (one sentence) | 100% | 94% | 20% | 0% | $0.0033 |
| **concise (three sentences)** | 91% | 97% | **0%** | 0% | $0.0034 |
| strict (a page of rules) | 87% | 97% | 2% | 0% | $0.0039 |

Raw runs in `evals/results/`.

### Amendment, 2026-09-04: these were single runs

Week 3 measured this pipeline's run-to-run variance by running one identical
config twice. Within a single process the two runs agreed on all 45 questions.
Across processes, the same config scored 84% and then 87% — a drift of roughly
two questions, despite `temperature=0.0`.

Every row in the table above is a single run, so each carries error bars of
about +/-2 questions. That changes what can honestly be claimed:

- **naive vs concise, 100% against 91%** — nine points, comfortably outside the
  noise. The finding stands.
- **concise vs strict, 91% against 87%** — four points, close enough to the
  noise floor that it is not a safe conclusion. The *direction* was consistent
  with the q_025 instruction-quoting failure, which is a qualitative
  observation rather than a statistical one, and that is the honest strength of
  the claim.
- **hallucination 0% across all three** — a floor, not a difference. Unaffected.

The decision does not change: concise ships, because the naive prompt's 20%
uncited answers is a large and unambiguous defect. But "a page of rules is
measurably worse than three sentences" is an overclaim from this data, and
would need repeated runs to support.

Logged as MISTAKES.md entry 18.

## Alternatives considered

### naive — one sentence

> Answer the security questionnaire question using the policy extracts provided.

- **Why it's attractive:** it scored the highest answerable accuracy of the three, 100%. It
  never confused a negative answer for a refusal, which is the bug the other two have.
- **Why I did not pick it here:** 20% of its answers claimed to be answerable while citing
  nothing at all. One answer in five had no source. For a product whose entire promise is
  that every answer traces to a document an auditor can open, an uncited answer is not a
  slightly worse answer — it is a worthless one. The 100% is a trap, and it is a good
  reminder that the headline metric is not always the metric that matters.
- **When it would be the better call:** any task where traceability is not the product.

### strict — a full page of numbered rules

- **Why it's attractive:** it is what careful prompt engineering is supposed to look like.
  Explicit rules, ordered by importance, a worked example of the SOC 2 distractor, and a
  closing line about the stakes.
- **Why I did not pick it here:** it was the worst of the three, and it got worse the more I
  added. I wrote rule 3 specifically to fix the "the answer is no" confusion described below;
  adding it dropped answerable accuracy from 91% to 87%. On `q_025` the model returned
  *"The policy corpus does not cover this and say what would be needed"* — my own schema
  description, quoted back verbatim as the answer. It had started copying the instructions
  rather than following them.
- **When it would be the better call:** possibly on a larger model with more capacity to
  spare. I have not tested that, and I should not claim it. What I can say is that on Nova
  Lite, instructions compete with the task for a limited budget of attention.

## The finding that changes the design

**Hallucination is 0% under every prompt, including the lazy one-sentence version.**

That is not a small detail. It means the system prompt is not what prevents hallucination.
The **schema** is. Making `answerable` a required boolean forces the model to commit to that
decision before it writes any prose — and it held on all five unanswerable questions,
including the three carrying deliberate lexical distractors, where retrieval returns text
that is *about* the topic without stating the fact. The SOC 2 question retrieves a passage
containing the literal string "SOC 2 Type II report", about what we require of our vendors.
Even the lazy prompt refused it.

The generalisable version: structured output is a guardrail, not a formatting convenience.
Choosing what fields the model is *required* to fill in shapes its behaviour more reliably
than telling it what to do in prose. A required boolean is a decision the model cannot skip;
a sentence in a system prompt is a suggestion it can drift past.

That reframes where to spend effort in weeks 3 to 5. When the answer quality is wrong, the
first question is now "what should the schema require?" rather than "how should I reword the
prompt?".

## Consequences

**Good:** zero hallucinations and zero uncited answers on the eval set, with the guarantee
coming from a schema rather than from wording that a model update could quietly invalidate.
Citation precision is 97%. The whole run costs $0.0034. And because the prompt is imported
rather than copied, there is no way to evaluate one thing and ship another.

**Bad:** I ship at 91% answerable accuracy, accepting a known and reproducible bug. On
`q_015`, `q_020` and `q_033` the model produced a *correct* answer — "No, engineers do not
get unrestricted rights over live systems" — and then set `answerable: false`. It conflates
"the answer is no" with "I cannot answer". I tried to fix it in the prompt and made things
worse (MISTAKES.md entry 14).

What I would try next, in order: rename the field from `answerable` to something that cannot
be misread as "is the answer yes", such as `supported_by_extracts`; or split it into two
required fields, one for whether the extracts support an answer and one for the answer's
polarity. Both are schema changes rather than prompt changes, which is exactly what the
finding above suggests.

## A note on the refusal cascade

Refusal is scored as a cascade, cheapest signal first: the structured `answerable` flag, then
a substring check for refusal language in the answer text, then an LLM judge only where those
two disagree. The design intent was cost — most cases resolve for free, and only ambiguous
ones pay for a judge call.

Its real value turned out to be different. It found all three "answer is no" bugs
immediately, with no judge call: the flag said refused, the substring check said the text was
plainly not a refusal, and the disagreement surfaced the contradiction. Two cheap signals
that ought to agree are a bug detector, not just a cost optimisation.

**Its limit matters just as much.** If retrieval returns the vendor SOC 2 passage and the
model answers confidently from it, the flag says answerable and the text contains no refusal
language. Both cheap signals agree, and both are wrong. At evaluation time the band label
catches that for free — `q_036` is labelled unanswerable, so any `answerable: true` is wrong
by definition. **At runtime there is no label, and nothing in this design catches it.**

That is the specific, measured argument for week 3's verifier being a *separate agent*
checking claims against retrieved text, rather than the answering model checking its own
work. A model that has already convinced itself is not the right thing to ask.

## The interview answer

"I tested three system prompts against a fixed eval set and the longest one lost — it dropped
accuracy from 91% to 87% and the model started quoting my instructions back as answers. The
finding that actually changed my design was that hallucination was 0% under all three,
including a one-sentence prompt. So the prompt wasn't preventing hallucination; the schema
was. Making `answerable` a required boolean forces that decision before any prose is written.
I now treat structured output as a guardrail rather than a formatting choice."
