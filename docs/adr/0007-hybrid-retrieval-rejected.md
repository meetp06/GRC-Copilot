# ADR-0007: Hybrid BM25 + vector retrieval, tried and rejected

**Status:** Accepted
**Date:** 2026-09-04

## Context

Dense embeddings compress meaning. That is exactly what makes them beat keyword search on
paraphrased questions — and exactly why they are weak on strings that must match literally.

This domain is full of those strings. `SC-28`, `AES-256`, `TLS 1.2`, `CloudTrail`, `800-53`.
A security questionnaire asks for them by name, and an auditor checks them character by
character.

The observation that pushed me to try hybrid search was concrete. Searching the vector index
for a bare `SC-28` returns the correct section — `risk-management-policy.md :: Control
mapping summary` — at rank 1, with a cosine score of **0.110**. Fifth place scores 0.084.
The right answer wins by 0.026, which is noise. Compare that to a well-phrased question like
"how quickly do you remediate critical vulnerabilities", which scores 0.740 and beats second
place by 0.35. On exact tokens the retriever is not confident, it is lucky.

BM25 finds `SC-28` instantly, because a term appearing in 1 of 58 chunks is overwhelming
evidence. Running both and fusing the results is the textbook fix.

## Decision

**Rejected.** Pure vector search ships. BM25 and the RRF fusion code stay in the repository,
tested, unused by the default path — because the reason for rejecting them is a property of
this corpus at this size, and that property is expected to change in week 4.

## The measurement

Top-5 over the 40 answerable golden-set questions:

| Config | easy | medium | hard | exact | ALL recall | MRR |
|---|---|---|---|---|---|---|
| Vector only | 100% | 100% | 92% | 90% | **97%** | 0.93 |
| Blind RRF fusion | 100% | 73% | 77% | 100% | 84% | 0.76 |
| Routed on literal tokens | 100% | 93% | 88% | 100% | 95% | 0.90 |

Fusion weight sweep (weight applied to the BM25 ranking, RRF k=60):

| w_keyword | 0.0 | 0.2 | 0.3 | 0.5 | 0.7 | 1.0 |
|---|---|---|---|---|---|---|
| ALL recall | **98%** | 90% | 84% | 84% | 84% | 82% |

Monotonic. Every amount of BM25 is worse than none, and no weight rescues it.

## Alternatives considered

### Blind RRF fusion — both retrievers, every query

- **Why it's attractive:** it is the standard recipe, it needs no query classification, and
  it did what it was supposed to on the band it exists for: the `exact` band went from 90%
  to 100%.
- **Why I did not pick it here:** there are only five slots. Vector search already fills them
  correctly 97% of the time, so every slot BM25 wins is a slot taken from a correct answer.
  The `medium` band — paraphrased questions with no shared vocabulary — collapsed from 100%
  to 73%. BM25 has no idea on those questions, but it votes anyway, handing back its best
  guess from a bad list, and RRF counts that vote as though it meant something.
- **When it would be the better call:** when neither retriever is dominant. Fusion assumes
  two roughly comparable opinions; here one retriever is far better on 15 of 40 questions,
  so its partner's votes are mostly noise injection.

### Routing — use BM25 only when the query contains a literal identifier

- **Why it's attractive:** it keeps BM25 for the case it wins and keeps it out of the way
  otherwise. It got closest: 95% overall, with `exact` at 100%.
- **Why I did not pick it here:** still below pure vector's 97%, so it pays for the exact
  band with losses in `medium` (93%) and `hard` (88%). The rule fires on questions like *"How
  do you keep passwords and API keys out of your codebase?"* — which contains an all-caps
  token and is nonetheless a meaning question, not a lookup. The classifier is doing pattern
  matching on the surface of the query while the thing it needs to know is the query's
  intent.
- **When it would be the better call:** with a classifier that is actually reliable, or once
  the exact band's win is large enough to outweigh the routing errors.

### Routing on document frequency rather than a hand-written pattern

- **Why it's attractive:** data-driven and self-maintaining. "Route to BM25 if the query
  contains a term that appears in very few chunks" needs no regex and adapts as the corpus
  changes.
- **Why I did not pick it here:** it fired on 38 of 40 questions. At 58 chunks of roughly 80
  tokens each, even `do`, `what`, `own` and `they` appear in two or fewer chunks. Inverse
  document frequency needs a corpus large enough for common words to actually be common,
  and mine is not. This is worth recording as a genuine limit: IDF is a statistic, and
  statistics on 58 samples of 80 tokens do not carry information.
- **When it would be the better call:** on a corpus of thousands of chunks, where document
  frequency separates real rarity from small-sample noise.

## Why RRF specifically failed here

Reciprocal Rank Fusion deliberately throws the scores away and keeps only the positions —
that is its selling point, because it removes the need to normalise a cosine similarity
running roughly 0.1 to 0.7 against a BM25 score that is unbounded and can reach 8.

But in this system the scores were carrying the most useful signal available. Vector search
*knew* it was unsure about `SC-28` (0.110, a 0.026 margin) and *knew* it was confident about
remediation timelines (0.740, a 0.35 margin). BM25 *knows* when it matched nothing at all,
because its score is exactly zero. Fusion discards all of it and treats "BM25's best of a bad
list" identically to "BM25's confident exact match on a term appearing once in the corpus".

The lesson generalises past this project: rank fusion is the right tool when you cannot trust
your scores to be comparable. When one retriever's score is a genuine confidence signal,
converting it to a rank is throwing away the thing you most needed.

## Consequences

**Good:** the shipped retriever is one component, not two plus a fusion policy plus a
classifier — and it scores higher. The rejection is backed by a weight sweep rather than a
single run, which makes it a finding instead of an anecdote. And BM25 exists, tested, so
re-running this comparison in week 4 costs an afternoon rather than a rebuild.

**Bad:** I ship a retriever with a known, named weakness. A questionnaire asking for a bare
control ID gets an answer that is correct by a margin of 0.026, and I have no confidence
signal that would let me flag it for human review — a 0.110 top hit and a 0.740 top hit are
treated identically downstream. That gap is real and unaddressed.

## Two caveats that keep this honest

**The exact band is five questions.** 90% versus 100% is a single gold chunk. That is not
enough evidence to conclude much in either direction, and I should not pretend otherwise.

**Vector recall is 97% largely because 58 chunks is a tiny corpus.** With 58 candidates,
top-5 is 8.6% of everything — dense retrieval barely has room to be wrong. On a corpus of
thousands of chunks, dense recall drops and exact-token matching matters much more. **I
expect this result to reverse at week 4 scale.**

So the decision is not "hybrid search is bad". It is "hybrid search does not pay for itself
on 58 chunks". The code is kept and tested precisely so the comparison gets re-run against
the real corpus, and this ADR gets superseded rather than quietly forgotten.

## A note on how this nearly went wrong

The first version of the golden set had 35 questions and not one of them asked for a literal
token. Against that set, hybrid search lost on every band and there was nothing to weigh
against the loss. I nearly rejected BM25 on a test that could only measure its damage and
never its benefit.

Adding the five-question `exact` band changed the picture — and did not change the decision,
which is what makes the decision worth trusting. Logged as MISTAKES.md entry 17.

## The interview answer

"I added hybrid search because dense retrieval scores 0.110 on a bare control ID — right
answer, no confidence. BM25 fixed that band, 90% to 100%, and made overall recall worse,
97% down to 84%, at every fusion weight I tried. There are only five slots and vector search
was already filling them; RRF also throws away the scores, which were the most informative
signal I had. So I rejected it and wrote down why I expect that to reverse once the corpus is
real — and I kept the code so I can re-run the comparison instead of rebuilding it."
