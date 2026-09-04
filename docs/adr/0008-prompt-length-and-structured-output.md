# ADR-0008: Concise prompt over strict, and why the schema does the real work

**Status:** Proposed
**Date:** 2026-09-04

<!--
SCAFFOLD. Evidence is real and measured. Prose is yours.
Delete every HTML comment when you're done.
Reproduce with: python -m src.rag.evaluate_answers [naive|concise|strict]
Raw runs: evals/results/
-->

## Context

<!--
TODO — 3-5 sentences covering:
  - week 1 asked for JSON in the prompt and parsed it back out by hand; it broke
    on a correct answer prefixed with <thinking> (MISTAKES.md entry 7)
  - week 2 replaced that with a forced tool call: the tool's input schema IS the
    answer shape, so there is nothing left to parse
  - once the shape was fixed, the open question became what to put in the system
    prompt, and that had to be decided on numbers rather than taste
-->

## Decision

<!-- TODO — name the prompt that ships and where it lives. -->

## The measurement

All 45 golden-set questions, one Nova Lite call each, identical retrieval and identical
tool schema. Only the system prompt changed.

| Prompt | answerable accuracy | citation precision | answered w/o citing | hallucination | cost |
|---|---|---|---|---|---|
| naive (one sentence) | 100% | 94% | 20% | 0% | $0.0033 |
| concise (three sentences) | 91% | 97% | 0% | 0% | $0.0034 |
| strict (a page of rules) | 87% | 97% | 2% | 0% | $0.0039 |

## Alternatives considered

### naive — one sentence

- Why it's attractive: <!-- TODO — highest answerable accuracy of the three -->
- Why I did **not** pick it here: <!-- TODO — 20% of its answers claimed to be answerable while citing nothing. An uncited answer cannot survive an auditor, which is the product's entire promise. The 100% is a trap. -->
- **When it would be the better call:** <!-- TODO -->

### strict — a full page of numbered rules

- Why it's attractive: <!-- TODO -->
- Why I did **not** pick it here: <!-- TODO — worst of the three. Adding rule 3 to FIX the "answer is no" bug dropped accuracy 91% -> 87%, and on q_025 the model quoted the instruction text back as its answer. -->
- **When it would be the better call:** <!-- TODO — would a larger model behave differently? Say what you believe and that you have not tested it. -->

## The finding that changes the design

<!--
TODO — write this out properly, it is the most transferable thing you learned:

Hallucination is 0% under EVERY prompt, including the lazy one-sentence version.
So the system prompt is not what prevents hallucination. The SCHEMA is. Making
`answerable` a required boolean forces the model to commit to that decision
before it writes any prose, on all 5 unanswerable questions including the 3
carrying lexical distractors.

Structured output is a guardrail, not a formatting convenience. Say it in your
own words and say what it implies for the rest of the system.
-->

## Consequences

**Good:** <!-- TODO -->

**Bad:** <!-- TODO — you ship at 91%, accepting a known bug: the model conflates "the answer is no" with "I cannot answer" and sets answerable=false on a correct negative answer. It happened on q_015, q_020, q_033. You tried to fix it with a prompt rule and made things worse. Say what you'd try next. -->

## A note on the refusal cascade

The scoring cascade — the structured `answerable` flag, a substring check for refusal
language, and an LLM judge only where those disagree — found all three of those bugs for
free, with no judge call. The flag said refused; the substring check said the text was not
a refusal; the disagreement surfaced it.

<!--
TODO — add the limit, because it matters: if retrieval returns the vendor SOC 2
passage and the model answers confidently from it, the flag says answerable and
the text contains no refusal language. Both cheap signals agree and both are
wrong. At eval time the band label catches that for free. At runtime nothing
here does. Name what has to catch it instead.
-->

## The interview answer

<!-- TODO — one sentence. -->
