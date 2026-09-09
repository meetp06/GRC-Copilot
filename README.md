# GRC Copilot

Automates security-questionnaire responses for companies selling software to enterprise
buyers.

## The problem

A startup sells software. A large enterprise wants to buy it. Before signing, the
enterprise's security team sends a 200-question security questionnaire (SIG, CAIQ, or their
own spreadsheet): *Do you encrypt data at rest? Who can access customer data? How fast do
you patch critical CVEs?*

The startup already has these answers — buried across policy PDFs, past questionnaires, and
people's heads. Answering takes an analyst 2-4 days of copy-paste. The deal waits.

It looks like a search problem. It isn't. Every answer needs a citation to a source document,
because an auditor will check it. And a wrong answer isn't a bad search result — it's a false
attestation to a customer. **The system has to know when it doesn't know.**

## What this builds

Upload a questionnaire. A multi-agent system:

1. Retrieves relevant text from the company's own policy corpus (hybrid search)
2. Drafts an answer
3. A separate verifier agent checks every claim actually appears in the source
4. Attaches a citation (document, section)
5. Maps the answer to a NIST 800-53 control
6. Scores confidence, auto-answers the confident ones, routes the rest to human review

2 days becomes ~20 minutes of review-and-approve. Every answer is traceable to a source
document, so it survives an auditor.

**Sold to the startup, not the enterprise.**

## Try it

There is a browser UI at `/ui`:

```
connect ─▶ upload ─▶ watch it answer ─▶ approve or reject ─▶ download the CSV
```

It is **not currently deployed**, and that is deliberate. Two KMS customer-managed keys cost
$1/month each whether or not anyone calls the API, and this project's budget is $5/month
(`docs/COST-GUARDRAILS.md`). The whole stack is 27 OpenTofu resources and comes up in about
four minutes -- `docs/aws/DEPLOY.md` has the four commands. It ran live on 2026-09-07;
`MISTAKES.md` 35-49 is what that cost me.

Locally, `uvicorn src.api.main:app` and open `http://127.0.0.1:8000/ui`.

`data/questionnaires/vendor_assessment.csv` is a 17-question third-party assessment written
against the deployed corpus. Four of its questions — recovery objectives, SOC 2, bug bounty,
TLS version — have no answer in that corpus, and the system refuses them. That is the thing
worth watching, not the thirteen it answers.

Prefer the raw API? `/docs` is the OpenAPI console; `/` lists every endpoint.

## Status

| Week | Focus | Status |
|------|-------|--------|
| 1 | Raw agent loop, no framework, Bedrock | ✅ Complete |
| 2 | RAG + golden eval set | ✅ Complete |
| 3 | LangGraph multi-agent + human-in-the-loop | ✅ Complete |
| 4 | Data pipeline + control ontology | ✅ Complete |
| 5 | FastAPI + SDK + MCP + observability | ✅ Complete |
| 6 | Terraform + CI/CD + threat model | ✅ Complete |

*Keep this table current. It's the first thing anyone reads.*

### What week 1 measured

The naive pieces were built to fail in specific, measurable ways. They did:

| Measurement | Result |
|---|---|
| Keyword search vs. paraphrased questions | **8 of 12 missed**, 7 of them answerable from the corpus |
| Vague tool description (`"Searches things."`) | **2.2x tokens** for the same answer — 3 steps to 6 |
| Step cap (`MAX_AGENT_STEPS=2`) | Fires correctly, run halts |
| Token budget, checked before each call | Fires correctly (`907 >= 100`, stopped at step 2) |
| Repeated-call guard | Runaway did **not** reproduce on Nova Lite — it gives up and answers |
| Total AWS spend, week 1 | ~$0.005 |

`patch != remediation`, `severe != critical`, `breach != incident`. The corpus answers the
question; keyword search cannot see it. That is the argument for embeddings in week 2 — a
measured baseline rather than an assumption.

### What week 2 measured

Corpus grew from 4 documents to 12 (58 sections). The eval set is
[`evals/golden_set.yaml`](evals/golden_set.yaml) — 45 questions across five bands, written
before any retrieval work so every change below is a number, not an opinion.

**Retrieval**, top-5 over the 40 answerable questions. `medium` is paraphrased with no shared
keywords; `exact` is a literal token such as `SC-28` or `AES-256`:

| Retriever | easy | medium | hard | exact | ALL recall | MRR |
|---|---|---|---|---|---|---|
| Keyword (week 1 baseline) | 100% | 33% | 50% | 80% | **60%** | 0.53 |
| Vector (Titan V2, section chunks) | 100% | 100% | 92% | 90% | **97%** | 0.93 |
| Hybrid (vector + BM25, RRF) | 100% | 73% | 77% | 100% | **84%** | 0.76 |

**Hybrid was tried and rejected on the numbers.** BM25 fixes the exact band (90% → 100%) and
costs more than that everywhere else, because with only five slots and vector search already
at 97%, every slot BM25 wins displaces a correct answer. Sweeping the fusion weight degraded
monotonically. Expected to reverse on a real corpus — see ADR.

**Chunking**, measured against the 34 distinct gold sections:

| Strategy | chunks | median tokens | sections/chunk | gold sections intact |
|---|---|---|---|---|
| Section-aware | 58 | 79 | 1.00 | **34/34** |
| Fixed 512/64 | 13 | 395 | 4.54 | 33/34 |
| Fixed 128/16 | 46 | 128 | 2.20 | **17/34** |

Small chunks cut answers in half; large chunks stop discriminating. At 512 tokens the window
exceeds most documents, so a "chunk" is nearly a whole policy and top-5 returns 38% of the
corpus.

**Answering**, all 45 questions, one Nova Lite call each, answer shape forced by a tool schema:

| Prompt | answerable accuracy | citation precision | answered w/o citing | hallucination |
|---|---|---|---|---|
| naive (one sentence) | 100% | 94% | **20%** | 0% |
| **concise (shipped)** | 91% | 97% | **0%** | 0% |
| strict (a page of rules) | 87% | 97% | 2% | 0% |

Hallucination is 0% under every prompt including the lazy one — the **schema** prevents it,
not the instructions. Making `answerable` a required boolean forces that decision before any
prose is written. The naive prompt's 100% is a trap: a fifth of its answers cite nothing, and
an uncited answer cannot survive an auditor.

Longer prompts made this model *worse*, monotonically. Raw runs in [`evals/results/`](evals/results/).

The four decisions behind these numbers: [ADR-0005 chunking](docs/adr/0005-chunking-strategy.md), [ADR-0006 vector store](docs/adr/0006-vector-store.md), [ADR-0007 hybrid rejected](docs/adr/0007-hybrid-retrieval-rejected.md), [ADR-0008 prompt length](docs/adr/0008-prompt-length-and-structured-output.md).

| Measurement | Result |
|---|---|
| Total AWS spend, week 2 | ~$0.03 |

### What week 3 measured

A 50-question questionnaire, end to end:

> **38 of 50 auto-answered, every one with a citation. 12 flagged for review. 44 seconds. $0.008.**

Of the 12 flagged, 6 are correct refusals — SOC 2, FedRAMP, HIPAA BAA, bug bounty, cyber
insurance twice. One of those (`q_050`) was never in the eval set and asks about insurance in
different words to the one that was; it was refused too.

**Confidence calibration** over the 45-question golden set. Confidence decides what ships
without a human reading it, so the number has to mean something:

| Band | n | correct | precision |
|---|---|---|---|
| high | 31 | 31 | **100%** |
| medium | 2 | 2 | 100% |
| low | 12 | 5 | 42% |

Compared against the model's own stated confidence, scored identically:

| Model said | n | precision |
|---|---|---|
| high | 36 | 92% |
| low | 9 | 56% |

The model called 36 answers high and was wrong on 3. The computed score — verifier passed
first time, retrieval margin, whether anything was cited, model opinion as the weakest
tiebreak — marked 31 high and was wrong on none, moving those 3 where a human catches them.
A model's confidence comes from the same pass that produced the answer, so it is not
independent evidence about it.

**Durability**, demonstrated rather than assumed. A process answered three questions and
`SIGKILL`ed itself; a second process read back two finished and one parked at
`('human_review',)` with 1173 input tokens spent. Resuming it there left the count at 1173 —
nothing re-ran. That unchanged number is the whole justification for adopting a framework.

**Concurrency**, measured rather than guessed. The week 3 plan predicted early Bedrock
throttling; it never appeared. 50 questions at concurrency 4 / 20 / 50 took 17.2s / 15.7s /
10.7s with zero retries and zero errors. The default is now 20, at the knee.

**The verifier is not a clear win**, and is recorded that way: −4 points of answerable
accuracy and 2× cost, for +2 points of citation precision and a runtime guard against
subject-drift claims the eval set cannot see. See
[ADR-0010](docs/adr/0010-graph-topology-and-the-verifier.md).

Decisions: [ADR-0009 framework choice](docs/adr/0009-langgraph-over-a-hand-written-loop.md),
[ADR-0010 topology and verifier](docs/adr/0010-graph-topology-and-the-verifier.md),
[ADR-0011 checkpointing](docs/adr/0011-sqlite-checkpointer-and-thread-per-question.md).

| Measurement | Result |
|---|---|
| Total AWS spend, week 3 | ~$0.05 |

### What weeks 4 and 5 built

**Week 4 — real documents.** Five public university and government PDFs in, three usable
markdown documents out. The two rejections are the point: one had no recoverable structure,
and one was a 70-page PowerPoint about incident response that would otherwise have been
indexed and cited to a customer as company policy.

```
read PDFs → parse → write markdown → build index
                 ↘ document catalog
```

Headings come from a cascade — text patterns, then font size and weight, then refusal —
and which method won is recorded per document. Retrieval on the real corpus: **92% recall**
against a 15-question golden set written for it, down from 97% on the hand-written one, with
MRR falling 0.93 → 0.63 because real sections are five times larger.

**The control ontology.** The eight-control dictionary is replaced by NIST SP 800-53 Rev 5.2.0
loaded from NIST's own OSCAL JSON — 20 families, 324 base controls, 1,196 with enhancements —
plus a hand-built SOC 2 crosswalk.

| Report | Result |
|---|---|
| NIST controls with no policy behind them | **311 of 324** |
| SOC 2 criteria with no policy at all | **24 of 37** |
| `"Do you have an incident response plan?"` | → IR-04, IR-08 → CC7.3, CC7.4, CC7.5 |

That last row is the product claim: answer once, and the same answer serves a NIST
questionnaire and a SOC 2 one. Every machine-proposed mapping stays unconfirmed until a named
person accepts it — an embedding score is not a basis for telling an auditor a control is
satisfied.

The mapper is scored against [a labelled set](evals/control_mapping_set.yaml), not eyeballed.
At the threshold originally shipped it was **24% precise** — 3 of every 4 mappings wrong — and
the first gap figures here said 274 and 15 because those bad edges counted as coverage.
Measured and retuned to 0.50: **78% precision**, false positives 37 → 2, at the cost of recall
falling 38% → 22%. That trade is deliberate: a missed mapping appears as a gap someone fixes,
a wrong one appears as coverage nobody rechecks.

**Week 5 — three ways in.**

```
graph ─▶ HTTP API   ─▶ POST /questionnaires → 202 + job_id → poll → answers
      ↘ Python SDK  ─▶ typed client, polling with backoff, named errors
      ↘ MCP server  ─▶ ask inside Claude or Cursor, no server needed
```

A 200-question run takes four minutes, which is longer than a load balancer will hold a
connection, so `POST` returns **202 Accepted** and the work happens in the background.

Per-question telemetry, from the first run through the API:

| | |
|---|---|
| Cost per question | **$0.000305** |
| Latency median / p95 | 2519 ms / 3289 ms |
| Uncited answers | **0** |

Decisions: [ADR-0012 Dagster](docs/adr/0012-dagster-for-ingestion.md),
[ADR-0013 ontology](docs/adr/0013-control-ontology-in-sqlite.md),
[ADR-0014 async jobs](docs/adr/0014-async-jobs-over-blocking-requests.md),
[ADR-0015 three interfaces](docs/adr/0015-three-interfaces-one-core.md).

| Measurement | Result |
|---|---|
| Total AWS spend, weeks 1-6 | ~$0.10 plus ~$2.40/month while deployed |

> **Deployed?** Run `tofu -chdir=infra destroy` when you are done demonstrating it.
> The two KMS keys bill whether or not anyone calls the API.

### What week 6 deployed

Deployable to AWS in four minutes, with a browser UI at `/ui`. `git push` runs the checks; `tofu apply` deploys, `tofu destroy` takes it down to nothing.

```
API Gateway (HTTP API) ─▶ Lambda (FastAPI via Mangum) ─▶ Bedrock
                                  ↘ S3        index + ontology
                                  ↘ DynamoDB  jobs + checkpoints
```

Answering a questionnaire against the deployed API:

| Question | Result |
|---|---|
| "Do you apply least privilege to information access?" | approved, cites *AO 48 :: Access Control* |
| "Do you have an incident response plan?" | approved → IR-01/04/08 → CC7.3/7.4/7.5 |
| "Are you SOC 2 Type II certified?" | **needs_review** — *"The policy corpus does not cover this."* |

Approving the third one through `/reviews/{job}/{question}/approve` resumed a graph that had
paused in a **Lambda container that no longer existed**. That is the week 3 durability claim
across machines rather than processes.

**27 resources, ~$2.40/month idle** — almost entirely two KMS keys. DynamoDB on-demand and
Lambda are $0 when nothing runs, which is why they are here rather than RDS and ECS.

**Four bugs appeared only in production**, and the worst one is the useful one: three of my
string-replace patches had silently done nothing because the file was reformatted between
edits, so the cross-tenant thread-namespacing fix never reached the code that writes
checkpoints. Found by reading the live DynamoDB partition keys — they said `e3`, not
`{job}:e3`. See MISTAKES 39-42.

**Security**, in [docs/THREAT-MODEL.md](docs/THREAT-MODEL.md): seven threats with what is
implemented against each and, where partial, exactly how partial. Prompt injection is
described as mitigated and not solved, because it is not solved.

CI runs lint, offline tests, gitleaks, bandit, pip-audit, `tofu validate` and tfsec on every
pull request, plus an opt-in eval gate that fails the build when retrieval drops below
measured floors. **CI deliberately cannot deploy** — that needs an OIDC role, and a pipeline
that can deploy is a pipeline whose credentials can.

Decisions: [ADR-0016 OpenTofu](docs/adr/0016-opentofu-over-terraform.md),
[ADR-0017 serverless](docs/adr/0017-serverless-and-what-it-costs.md).

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pre-commit install

cp .env.example .env      # then edit it

aws configure --profile grc-copilot
python scripts/check_bedrock.py       # confirms access + lists YOUR model IDs
python -m src.agent.loop "Do you encrypt customer data at rest?"
```

## Architecture (current — week 1)

```
  question
     |
     v
  +---------------------------+
  |  raw agent loop           |     while step < MAX_STEPS:
  |  (src/agent/loop.py)      |       1. send messages + tools to model
  |                           |       2. model returns text OR tool_use
  |  no framework on purpose  |       3. execute tool, append result
  +------------+--------------+       4. repeat
               |
     +---------+---------+
     |                   |
     v                   v
 search_policies    get_control_info
 (keyword, naive)   (hardcoded dict)
```

Week 3 replaces the hand-written loop with a LangGraph `StateGraph`. Building it by hand
first is deliberate — see [ADR-0003](docs/adr/0003-raw-loop-before-framework.md).

Everything naive here is naive on purpose. Each piece fails in a specific way that motivates
the next week's work.

## Documentation

| Document | What it's for |
|----------|---------------|
| [CLAUDE.md](CLAUDE.md) | Ground rules for Claude Code working in this repo |
| [docs/STUDY-GUIDE.md](docs/STUDY-GUIDE.md) | The whole build in one sitting — plain language, then the technical detail |
| [docs/ROADMAP.md](docs/ROADMAP.md) | The whole six-week plan |
| [docs/weeks/](docs/weeks/) | Detailed plan per week — tasks, hours, definition of done |
| [docs/TECH-CHOICES.md](docs/TECH-CHOICES.md) | Every technology, its alternatives, when each wins |
| [docs/MISTAKES-TO-HUNT.md](docs/MISTAKES-TO-HUNT.md) | Failures to trigger deliberately, per week |
| [docs/INTERVIEW-PREP.md](docs/INTERVIEW-PREP.md) | The two-minute story, question bank, JD mapping |
| [docs/COST-GUARDRAILS.md](docs/COST-GUARDRAILS.md) | AWS cost safety rules |
| [docs/THREAT-MODEL.md](docs/THREAT-MODEL.md) | Seven threats, and how partial each mitigation is |
| [docs/COMPLIANCE.md](docs/COMPLIANCE.md) | This product's own compliance posture, honestly |
| [docs/aws/DEPLOY.md](docs/aws/DEPLOY.md) | Deploying, and taking it down again |
| [docs/adr/](docs/adr/) | Architecture Decision Records |
| [MISTAKES.md](MISTAKES.md) | Running bug log |

## Cost

Target: **under $5/month.** See [COST-GUARDRAILS.md](docs/COST-GUARDRAILS.md).

The one rule worth repeating here: **never enable OpenSearch Serverless (Classic)** — it
bills roughly $350/month idle, and several AWS RAG tutorials use it without warning you.

## Limitations

Honest list, kept current. This section is a feature — it's what makes the rest credible.

- Prompt injection through uploaded documents is *mitigated, not solved*. Nobody has solved
  it. See the threat model (week 6).
- Runs in commercial AWS, architected against NIST 800-53 control patterns. **Not** GovCloud,
  **not** IL5, **not** FedRAMP-assessed. Those require an organizational sponsor.
- Single-tenant. Multi-tenant isolation is not implemented.
- Auth is an API key, not real per-tenant authorization.
- Retrieval is keyword matching, so it misses paraphrased questions (measured above). Week 2.
- Answers are parsed out of free text, so a chatty model can produce an unparseable answer.
  Week 2 replaces this with structured output via a tool call.
- `get_control_info` echoes unknown input back in its error string. Harmless for a control
  ID, but this product treats uploaded text as hostile — worth removing before real input.
