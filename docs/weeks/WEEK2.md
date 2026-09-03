# Week 2 — Real RAG and evaluation (target: 20 hours)

**Milestone:** a golden eval set of 30-50 questions with graded retrieval metrics, and
numbers proving hybrid retrieval + reranking beats the week 1 keyword search.

**Read first:** your own `MISTAKES.md` from week 1. The failures you logged are the
requirements for this week.

---

## The single most important idea this week

Build the evaluation set **before** you improve retrieval.

Everyone builds RAG. Almost nobody measures it. If you improve retrieval without a baseline,
you have an opinion. If you improve it against a fixed eval set, you have a number — and a
number is what you say in an interview.

This inverts the tutorial order on purpose. Expect it to feel slow on day 1 and obviously
correct by day 5.

---

## Day 1 — The golden eval set (5h)

Write 30-50 real security questionnaire questions against your `data/policies/` corpus.
Source them from public SIG Lite and CAIQ question banks, or write them yourself in the
style of a real questionnaire.

For each question record:

```yaml
- id: q_007
  question: "How quickly do you remediate critical vulnerabilities?"
  expected_source: vulnerability-management-policy.md
  expected_section: "Remediation timelines"
  expected_control: RA-5
  ground_truth_answer: "Critical findings are remediated within 7 days."
  category: vulnerability_management
  difficulty: easy
```

Deliberately include:

- **~10 easy** — direct keyword overlap with the policy text
- **~15 medium** — synonyms and paraphrase, no keyword overlap ("is client data protected
  when stored" for encryption at rest)
- **~10 hard** — answer requires combining two documents, or reasoning across sections
- **~5 unanswerable** — the corpus genuinely does not cover it (SOC 2 report, penetration
  test dates for a year you don't have, FedRAMP authorization). **These matter most.** A
  system that confidently invents a policy is worse than useless for compliance. Your
  metric here is: does it correctly refuse?

Store as `evals/golden_set.yaml`. Version it. Never edit an entry to make a run look better —
if a question is wrong, fix it and note the change.

## Day 2 — Chunking (3h)

Compare at least two strategies on your corpus and record the numbers:

1. **Fixed-size with overlap** (e.g. 512 tokens, 64 overlap) — the naive default
2. **Section-aware** — split on markdown headings, keep whole sections intact
3. Optional: **contextual retrieval** — prepend a one-line document summary to each chunk
   before embedding, so an isolated chunk carries the context of its parent document

Policy documents are structured. Section-aware will probably win. But *probably* isn't a
finding — measure it.

**Question to be able to answer:** why does chunk size trade off recall against precision?

## Day 2-3 — Embeddings and the vector store (4h)

Embedding model: use a Bedrock-hosted one (Titan Embeddings or Cohere Embed) so inference
stays in the same account as the data — that's the ADR-0002 argument extended.

Vector store — see `docs/TECH-CHOICES.md` for the full comparison. Short version:

- **Start with a local FAISS or a simple numpy index.** 4 documents and ~50 chunks does not
  need a database. Zero cost, zero setup, fast iteration.
- Move to S3 Vectors or pgvector in week 4 when the corpus is real.
- **Do not create an OpenSearch Serverless collection.** ~$350/month idle.

Yes, starting local means migrating later. That migration is a week 4 ADR and a good
interview story about premature infrastructure.

## Day 3-4 — Hybrid retrieval and reranking (5h)

**Why hybrid, specifically:** dense embeddings are good at meaning and bad at exact tokens.
Your domain is full of exact tokens — `SC-28`, `AES-256`, `TLS 1.2`, `CVE-2024-3094`. Ask
for "SC-28" and a pure vector search may return general encryption text while missing the
literal string. BM25 nails it. Run both, fuse the results (reciprocal rank fusion is a
reasonable default), then rerank.

Build in this order, measuring after each step:

1. Dense only → record metrics
2. Dense + BM25 fused → record metrics
3. Add a reranker over the top ~20 → record metrics

If a step doesn't improve the numbers, **say so in the ADR and consider dropping it.**
Negative results are more credible than a stack of techniques that all supposedly helped.

## Day 4-5 — Ragas and the numbers (3h)

Metrics to track per run:

| Metric | What it catches |
|--------|-----------------|
| context recall | Did we retrieve the passage that contains the answer? |
| context precision | Is the retrieved context mostly signal or mostly noise? |
| faithfulness | Is the generated answer actually supported by the retrieved context? |
| answer relevance | Does the answer address the question asked? |
| **refusal accuracy** (custom) | On the 5 unanswerable questions, did it correctly decline? |

Write results to `evals/results/YYYY-MM-DD-<config>.json` so you have a history. Put a
comparison table in the README.

Add the structured-output fix here too: replace the fragile `_parse_json_answer()` from week
1 with a tool call that forces the schema. Note in `MISTAKES.md` how often the old parser
actually failed — that's the justification.

---

## Break it on purpose

- **Retrieve top-1 only.** Watch faithfulness collapse on multi-part questions.
- **Retrieve top-20.** Watch precision drop and cost rise, and see whether answer quality
  actually improves. Usually it doesn't. Good "more context isn't better" story.
- **Ask a question about a policy you don't have.** Does it refuse, or invent? If it
  invents, that's the highest-severity bug in a compliance product. Fix the prompt, re-run
  the eval, record the before/after.
- **Embed the query with a different model than the documents.** Watch retrieval turn to
  noise. Explains why the embedding model is a hard dependency of the index.
- **Search for `SC-28` with dense retrieval only.** This is your BM25 justification, live.

---

## Definition of done

- [ ] `evals/golden_set.yaml` with 30-50 questions across four difficulty bands
- [ ] `python -m src.rag.evaluate` runs the whole set and writes a results file
- [ ] A before/after table: keyword baseline vs final config, on every metric
- [ ] At least one technique you tried and **rejected** on the numbers
- [ ] Structured output replaces the regex JSON parsing
- [ ] 3 new ADRs (vector store, chunking, hybrid vs dense)
- [ ] 3+ new `MISTAKES.md` entries
- [ ] Still under $5 total spend

## If you fall behind

Cut the reranker and contextual retrieval. Keep the eval set and hybrid search. The eval set
is non-negotiable — it's the thing that makes weeks 3 through 6 measurable.

## Interview answers you'll own after this week

- "How do you know your RAG system is any good?"
- "Why hybrid search instead of just embeddings?"
- "What's the failure mode of chunking too small?"
- "How do you stop a RAG system from hallucinating a policy that doesn't exist?"
