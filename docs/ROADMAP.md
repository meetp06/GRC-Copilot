# Roadmap

Six weeks, roughly 20 hours a week. Each week ends with something demonstrable and at least
one ADR.

The through-line: **start naive, measure the pain, then fix it.** Every sophisticated piece
of this system exists because a simpler version failed first, and I can show you the failure.
That's the difference between "I used a reranker" and "I used a reranker because my eval set
showed recall@5 was fine but precision@3 was terrible, and here are the numbers."

---

## The arc

| Week | Theme | Milestone | JD bullet |
|------|-------|-----------|-----------|
| 1 | Raw agent loop | Terminal in, cited JSON answer out | LLM, prompt engineering |
| 2 | Real RAG + evaluation | Measurable retrieval quality on a golden set | RAG, LLM |
| 3 | LangGraph multi-agent | Human approval gate, resumable runs | Multi-agent, LangGraph |
| 4 | Data pipeline + ontology | Ingest a real corpus, control mapping | ETL, metadata, ontologies |
| 5 | API + SDK + observability | REST API, Python SDK, MCP server, traces | REST APIs, SDKs |
| 6 | Deploy + secure + CI/CD | Terraform, GitHub Actions, threat model | DevOps, secure cloud |
| 7 | Story | Demo video, blog posts, design doc | Documentation, comms |
| 8+ | Stretch | Whatever an interview asked about | — |

---

## Week 1 — Raw agent loop ✅

**Built:** hand-written reason-act-observe loop over the Bedrock Converse API. Two naive
tools: keyword policy search, hardcoded control lookup. Three guardrails: step cap, token
budget, repeated-call detector.

**Deliberately naive:** keyword search instead of embeddings, dict instead of ontology, no
framework. Each of these fails in a specific way that motivates the next week.

**Detail:** `docs/weeks/WEEK1.md`

---

## Week 2 — Real RAG and, more importantly, evaluation

**Milestone:** a golden eval set of 30-50 questions, retrieval measured against it, and
numbers showing the improvement from naive keyword search to hybrid + rerank.

The eval set is the actual deliverable. Retrieval improvements are easy; knowing whether
they helped is what separates this from a tutorial. Build the eval set *before* you improve
retrieval, so you have a baseline to beat.

**Key work:**
- Chunking strategy (compare fixed-size vs section-aware on your corpus)
- Embeddings via Bedrock Titan or Cohere; vector store choice
- Hybrid retrieval: dense + BM25, because control IDs like "SC-28" are exact-match tokens
  that embeddings handle badly
- Reranking pass
- Contextual retrieval (prepend document context to each chunk before embedding)
- Ragas metrics: faithfulness, answer relevance, context precision, context recall

**ADRs to write:** vector store choice, chunking strategy, hybrid vs dense-only

**Detail:** `docs/weeks/WEEK2.md`

---

## Week 3 — LangGraph and human-in-the-loop

**Milestone:** the same behaviour as week 1, but as a `StateGraph`, with a real interrupt
that pauses the run for human approval and resumes from a checkpoint.

**Key work:**
- Port the hand-written loop to LangGraph, tools unchanged
- Supervisor topology: retriever → drafter → citation verifier → confidence scorer
- Reflection step: the verifier can send an answer back for a redraft
- `interrupt()` + checkpointer so low-confidence answers pause for a human
- Batch mode: process a 50-question questionnaire, not one question

**The interesting problem:** what state does each node need, and what happens if the process
dies mid-questionnaire? That's what the checkpointer buys you, and it's the honest answer to
"why a framework?"

**ADRs to write:** LangGraph over alternatives, graph topology, checkpointer backend

**Detail:** `docs/weeks/WEEK3.md`

---

## Week 4 — Data pipeline and the control ontology

**Milestone:** point the system at a folder of real policy PDFs and have it produce an
indexed, catalogued corpus with control mappings, on a schedule.

This is the week most portfolio projects skip, and it's the one FDE interviewers care about
most — because in the field, the data is always someone else's mess.

**Key work:**
- Dagster assets: parse → chunk → embed → index, with lineage
- Handle real-world document mess: scanned PDFs, tables, DOCX, inconsistent headings
- The control ontology: Question → Control → Policy Section → Evidence. This is the
  "ontology" bullet, done properly — a graph of relationships, not a lookup table
- Crosswalk NIST 800-53 to SOC 2 Trust Services Criteria, so one answer serves both
  questionnaire formats
- Metadata catalog: what document, what version, when ingested, who owns it, when it expires

**ADRs to write:** orchestrator choice, ontology model, document parsing strategy

**Detail:** `docs/weeks/WEEK4.md`

---

## Week 5 — API, SDK, MCP, observability

**Milestone:** someone else can use this without reading the code — through a REST API, a
Python client, or from inside Claude/Cursor via MCP.

**Key work:**
- FastAPI: submit questionnaire, poll status, list answers, approve/reject
- Async job handling, because a 200-question run takes minutes not seconds
- A thin Python SDK wrapping the API, published to TestPyPI
- MCP server exposing the same tools (use FastMCP)
- Langfuse tracing: every LLM call, cost per questionnaire, latency breakdown
- OpenAPI docs that are actually readable

**Why MCP matters here:** it's the difference between a demo and a thing that plugs into
where compliance people already work. Also currently a strong signal in interviews.

**ADRs to write:** async job design, MCP transport, observability stack

**Detail:** `docs/weeks/WEEK5.md`

---

## Week 6 — Deploy, secure, automate

**Milestone:** it's deployed from a git push, and there's a written threat model that shows
you thought about how this gets attacked.

**Key work:**
- Terraform for all infrastructure, remote state
- Lambda + API Gateway (serverless, so idle cost is near zero)
- GitHub Actions: lint, test, security scan, plan on PR, apply on merge
- OIDC instead of long-lived AWS keys in CI
- Security: KMS encryption, least-privilege IAM, CloudTrail, secrets in Secrets Manager
- Threat model covering prompt injection through uploaded documents — the real risk for
  this product
- The honest FedRAMP write-up: what NIST 800-53 controls this design satisfies, and a plain
  statement that this is commercial AWS, not GovCloud

**Detail:** `docs/weeks/WEEK6.md`

---

## Week 7 — The story

Code nobody can understand doesn't get you hired. Budget real time for this.

- 3-4 minute demo video: the problem, the run, the human approval, the traces
- A design doc written for a non-engineer stakeholder
- 2-3 blog posts on the genuinely interesting parts (the eval set, the injection threat
  model, what LangGraph actually bought over the raw loop)
- README polish: architecture diagram, honest limitations section
- Rehearse the two-minute story out loud until it's fluent

See `docs/INTERVIEW-PREP.md`.

---

## Stretch (only if an interview asks)

- Bedrock AgentCore as a managed runtime
- Multi-tenant isolation
- Fine-tuned classifier for question → control mapping
- Evaluation-driven prompt optimization (DSPy)
- A real frontend

---

## Rules for the whole build

1. **Apply for jobs starting week 3.** Don't wait for done. Interviews will tell you which
   parts matter, and you'll build those better.
2. **One ADR per real decision, the day you make it.**
3. **Log mistakes the day they happen.**
4. **Never enable OpenSearch Serverless Classic.** ~$350/month idle.
5. **If a week slips, cut scope, not documentation.** The docs are the deliverable.
6. **Ship something demoable every week**, even if ugly.
