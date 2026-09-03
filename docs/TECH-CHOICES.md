# Technology Choices

Every significant technology in this project, why it was chosen, what the alternatives were,
and — the part that matters — **when the alternative would be the better call.**

This is a planning reference. As each decision is actually made, write the real ADR in
`docs/adr/` with what you learned. Where an ADR exists it supersedes this file.

> **How to use this in an interview:** never say "X is better than Y." Say "I picked X here
> because of *this specific constraint*; if the constraint were *that* instead, Y wins."
> Engineers who talk in trade-offs sound senior. Engineers who talk in winners sound like
> they read a blog post.

---

## Model layer — AWS Bedrock

**Decided in ADR-0002.** Summary: Bedrock keeps inference in the same AWS account, region,
and audit trail as the customer's documents. For a compliance product, "where does my data
go" is the buyer's first question.

**Alternatives:** direct provider APIs (simpler, newer models sooner, worse data-residency
story); self-hosted open weights (cheapest at high volume, real air-gap story, needs a GPU
and weeks of infra work); Vertex AI or Azure OpenAI (equivalent, wrong cloud for this JD).

**Cost note:** Bedrock has no free tier. You pay from the first call. Verify current
per-model pricing before choosing — it changes.

---

## Agent orchestration — hand-rolled loop → LangGraph

**Decided in ADR-0003** for week 1. The week 3 framework decision:

### LangGraph — the choice
Graph of nodes over explicit shared state, with checkpointing and `interrupt()`.

**Why here:** the human approval gate needs durable state. A run has to survive being paused
for a day, or a crash. That's a real requirement, not a preference — and hand-rolling a
correct checkpointer is where a raw loop stops being reasonable. Cyclic graphs also give you
the reflection loop (verifier sends a draft back) naturally.

**Cost:** steeper learning curve than the alternatives. More boilerplate for simple flows.
The abstraction leaks when you're debugging.

### CrewAI
Role-based agents ("you are a security analyst") that collaborate.

**Attractive:** fastest path to a working multi-agent demo, very readable, low ceremony.

**When it wins:** role-delegation problems where agents are conceptually people —
researcher, writer, editor. Prototyping. When you need something demoable this week.

**Why not here:** less control over explicit state transitions, and weaker durable
checkpoint/resume, which is exactly the feature this product needs.

### Bedrock Agents / AgentCore
AWS-managed agent runtime — the loop runs server-side.

**Attractive:** no loop to maintain, managed memory and sessions, native AWS integration,
handles scaling.

**When it wins:** an ops team that wants a managed runtime rather than code to own; enterprise
AWS shops; when you want to deploy an existing agent without building infrastructure.

**Why not here:** it hides the loop, which is the thing you're trying to learn, and it costs
per invocation. Keep as a week 8 stretch — "I deployed my LangGraph agent onto AgentCore" is
a strong follow-up.

### OpenAI Agents SDK / Strands
Lightweight harnesses with handoffs and built-in tracing.

**When they win:** you're already on that provider; you want tracing without extra setup;
simpler multi-agent handoffs without graph ceremony.

### No framework at all
**When it wins:** single tool, no state, no human in the loop. A large fraction of
"agents" in production are one prompt and one tool call, and a framework is pure overhead
there. Say this in interviews — it signals judgment rather than hype.

---

## Vector store — local first, then managed

**Recommendation: start with FAISS or a numpy index (week 2), migrate in week 4.**

Fifty chunks does not need a database. Local costs nothing, sets up in minutes, and you
iterate fast. The migration later is itself a good ADR and a good story about not
provisioning infrastructure before you have data.

### The options, when the corpus is real

| Option | Idle cost | Best when |
|--------|-----------|-----------|
| FAISS / local | $0 | Prototyping, small static corpus, single process |
| **S3 Vectors** | very low, storage-priced | Infrequent queries, cost-sensitive, already on AWS |
| **pgvector (RDS/Aurora)** | moderate | You already need a relational DB; want SQL filters + vectors in one query |
| Pinecone / Weaviate / Qdrant Cloud | low free tier → moderate | Want managed, don't care about cloud lock-in, need scale fast |
| **OpenSearch Serverless (Classic)** | **~$350/month** | Never, for this project |

**The OpenSearch warning is the important line here.** It bills for minimum capacity units
whether or not you query it. Many AWS RAG tutorials use it and do not warn you. This has
generated a lot of surprise bills.

**pgvector deserves a real look for this project**, because the ontology is relational
(Question → Control → Section → Evidence) and you'll want to filter vector results by
metadata — "only chunks from documents reviewed in the last 18 months." One database doing
both is genuinely simpler than two.

---

## Retrieval strategy — hybrid, then rerank

**Dense embeddings alone are wrong for this domain.** Your corpus is full of exact tokens:
`SC-28`, `AES-256`, `TLS 1.2`, `CVE-2024-3094`. Embeddings represent meaning and are
unreliable on exact identifiers. BM25 is exact-match and nails them. Fuse both (reciprocal
rank fusion is a fine default), then rerank the top ~20.

**When dense-only is enough:** conversational corpora with no identifier vocabulary, or when
latency and cost matter more than the last few points of recall.

**When keyword-only is enough:** small corpus, users who know the exact terminology. Don't
dismiss it — it's free, instant, and interpretable. Week 1 proves where it fails.

**Contextual retrieval** (prepend a document-level summary to each chunk before embedding)
is cheap and usually helps with policy documents, because an isolated chunk loses its parent
context. Measure it; don't assume.

---

## Evaluation — Ragas plus a hand-built golden set

**The golden set is the real asset.** Ragas is just the metric implementation. 30-50
hand-written questions with known correct sources, including deliberately unanswerable ones,
is what makes every later change measurable.

**Alternatives:** LLM-as-judge alone (cheaper to build, noisier, and it drifts when the judge
model changes); human eval only (highest quality, doesn't scale, can't run in CI); DeepEval
or promptfoo (fine alternatives to Ragas — the framework matters much less than having a
fixed question set).

**Say this in interviews:** the tool is interchangeable, the eval set is not.

---

## Observability — Langfuse

Traces every LLM call with cost, latency, and the retrieval context that produced each answer.

**Why it matters here:** it produces the concrete numbers — cost per questionnaire, slowest
node, verifier rejection rate — that make you sound like you ran a system rather than built
a demo.

**Alternatives:** LangSmith (tighter LangChain/LangGraph integration, hosted, good if you're
all-in on that ecosystem); Arize Phoenix (strong on embedding drift analysis, OSS); plain
OpenTelemetry to CloudWatch (no LLM-specific views, but no new vendor).

---

## Data orchestration — Dagster

**Why:** asset-based. You declare *the data that should exist* and its lineage, rather than
*the tasks that should run*. When one document changes, you re-embed that document's chunks
only. The lineage graph is literally the "metadata catalog" bullet.

**Airflow — when it wins:** the company already runs it (most do); huge operator ecosystem;
you need time-based DAGs more than data lineage. It's the industry default and worth being
able to discuss even if you don't use it.

**Prefect — when it wins:** you want Python-native flows with minimal infrastructure and
dynamic, runtime-determined DAGs.

**Plain cron + scripts — when it wins:** genuinely simple pipelines. Be willing to say this.
Reaching for an orchestrator on a three-step pipeline is over-engineering, and interviewers
notice when you can name that.

---

## Ontology storage — SQLite (then Postgres)

Relational tables, not a graph database.

**Why:** at this scale the relationships are shallow — a handful of joins. SQL handles it
fine, everyone can read it, zero operational cost.

**Neo4j / a real graph DB — when it wins:** deep multi-hop traversal ("find all controls
transitively affected if this policy section is removed"), relationships genuinely
outnumbering entities, or graph algorithms like centrality. If the control ontology grows
inheritance chains and cross-framework crosswalks across five frameworks, revisit.

**RDF/OWL triple stores — when they win:** formal reasoning and inference, or interop with
published standards ontologies. Heavy for this.

**Saying "I used SQLite because a graph database would have been over-engineering at this
scale, and here's the specific query pattern that would change my mind" is a stronger answer
than using Neo4j.**

---

## API — FastAPI

Async by default, Pydantic validation, OpenAPI docs for free, the current Python default for
this kind of service.

**Flask — when it wins:** existing Flask codebase, or a very simple sync service.
**Django REST — when it wins:** you need an ORM, admin, and auth out of the box.
**Go or Node — when they win:** the team's language; extreme concurrency needs.

## MCP server — FastMCP

Use FastMCP. The `fastapi_mcp` auto-conversion path has been unreliable; wrapping your
service functions directly in FastMCP tools gives cleaner tool descriptions anyway — and the
tool description *is* prompt engineering, so you want control over it.

---

## Compute — Lambda + API Gateway

**Why:** idle cost near zero, which is the constraint that matters for a portfolio project
that must survive for months on a small budget.

**Real constraints to be able to discuss:** 15-minute execution limit (long questionnaires
need Step Functions or chunked invocations); 250MB unzipped package limit (ML dependencies
need container images or layers); cold starts.

**ECS/Fargate — when it wins:** long-running work, large dependencies, steady traffic where
per-request pricing stops being cheaper, or you need more than 15 minutes.
**EC2 — when it wins:** GPU inference, or you need specific instance control.

---

## IaC — Terraform

**Why:** the industry default, cloud-agnostic, huge module ecosystem, and the skill transfers
to any employer.

**AWS CDK — when it wins:** all-in on AWS and the team prefers writing infrastructure in
TypeScript or Python with real abstractions.
**CloudFormation/SAM — when they win:** pure serverless AWS, and you want zero extra tooling.
**Pulumi — when it wins:** you want general-purpose languages with strong typing over HCL.

---

## Things deliberately NOT used, and why

- **A frontend framework.** The API, MCP integration, and CLI demonstrate the same thing.
  Building React here would consume a week and prove nothing about the parts you're being
  hired for. If an interviewer asks for a UI, that's week 8.
- **Fine-tuning.** RAG plus prompting solves this problem. Fine-tuning would add cost,
  complexity, and a retraining pipeline for no measured gain. *Be ready to say what would
  change your mind:* a high-volume, narrow, repetitive classification step — like
  question → control mapping — where a small fine-tuned classifier could beat an LLM call on
  both cost and latency.
- **A multi-model router in week 1.** Premature. Add it when the traces show a specific
  expensive step that a cheaper model handles fine.
- **Kubernetes.** For one service with intermittent traffic, this would be pure ceremony.
