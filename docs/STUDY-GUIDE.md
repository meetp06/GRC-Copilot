# Study Guide

Read this once, start to finish. About 40 minutes.

Every week has the same five parts:

```
What we built ─▶ Why ─▶ The numbers ─▶ New words ─▶ Ask yourself
```

Plain language first. Technical detail after. Nothing here is invented — every number
comes from a file in this repo.

---

## Before week 1 — what the product is

**The situation**

```
startup wants to sell software to a big company
  ↘ big company sends a 200-question security questionnaire
    ↘ analyst spends 2-4 days copy-pasting from policy PDFs
      ↘ the deal waits
```

**What we built:** upload the questionnaire, get answers back with citations, a human
approves the uncertain ones, download the finished file.

**The one hard part:** a wrong answer is not a bad search result. It is a written promise
to a customer that an auditor will check later.

> The system must know when it does not know.

Everything else in this project is easier than that sentence.

---

# Week 1 — build it badly on purpose

## What we built

- An agent loop written by hand. No framework.
- Keyword search for finding policy text.
- A step cap and a token budget so a runaway loop cannot cost money.

## Why

Two reasons.

**One:** if I use a framework on day one, I cannot say what it replaced. In an interview
"why LangGraph?" needs an answer better than "it is popular".

**Two:** keyword search is meant to fail. I need a baseline that fails *in a way I can
measure*, not a guess that embeddings are better.

## The numbers

| Test | Result |
|---|---|
| Keyword search vs paraphrased questions | **8 of 12 missed** — 7 were answerable |
| Vague tool description (`"Searches things."`) | **2.2× the tokens**, 3 steps → 6 |
| Step cap and token budget | Both fire correctly |
| AWS spend | ~$0.005 |

**Why keyword search failed:**

```
question says: "how fast do you patch critical vulnerabilities?"
policy says:   "remediation of severe findings within 72 hours"

patch ≠ remediation
critical ≠ severe
```

Same meaning. Zero shared words. Keyword search sees nothing.

## New words

**Agent loop** — the model gets tools, picks one, sees the result, picks again, until it
answers. A `while` loop with an LLM deciding what happens next.

**Tool description** — the text telling the model what a tool does. A vague one costs real
money: the model calls the wrong tool, sees junk, tries again.

**Token budget** — a hard stop on spend, checked *before* each call, not after.

## Technical detail

- Model: Amazon **Nova Lite** on Bedrock. Cheapest capable model for a dev loop.
- `MAX_AGENT_STEPS=2` and a token ceiling, both enforced in Python, not in a prompt.
- A repeated-call guard was built. It never triggered — Nova Lite gives up and answers
  instead of looping. Written down as *did not reproduce*, not as *fixed*.

## Ask yourself

1. Why not use LangGraph from day one?
2. Why is `patch ≠ remediation` the whole argument for embeddings?

---

# Week 2 — the test set comes first

This is the most important week. Everything after rests on it.

## What we built

- A **golden set**: 45 questions, written *before* any retrieval code.
- 5 of those 45 have **no answer in the corpus** on purpose.
- Section-aware chunking.
- Vector search with Titan embeddings.
- A tool schema that forces the answer's shape.

## Why

If I build the system first and the test second, I will write a test the system passes.
Writing the test first means every later change is a **number**, not a feeling.

The 5 unanswerable questions are the point. A system that answers them is broken no matter
how good the writing is.

## The numbers

**Retrieval — did we find the right policy section? (top 5 results)**

| Retriever | medium | hard | exact | ALL | MRR |
|---|---|---|---|---|---|
| Keyword (week 1) | 33% | 50% | 80% | **60%** | 0.53 |
| **Vector (shipped)** | 100% | 92% | 90% | **97%** | 0.93 |
| Hybrid (vector + BM25) | 73% | 77% | 100% | **84%** | 0.76 |

**Hybrid was built and then thrown away.** BM25 fixes exact-match questions and breaks
everything else — with only 5 slots and vector already at 97%, every slot BM25 wins pushes
out a correct answer.

**Chunking — how do we cut documents into pieces?**

| Strategy | chunks | gold sections kept whole |
|---|---|---|
| **Section-aware (shipped)** | 58 | **34 / 34** |
| Fixed 512 tokens | 13 | 33 / 34 |
| Fixed 128 tokens | 46 | **17 / 34** |

Small chunks cut answers in half. Big chunks stop being specific — at 512 tokens a "chunk"
is nearly a whole policy, so top-5 returns 38% of the corpus.

**Answering — three prompts, same questions**

| Prompt | accuracy | cited properly | answered with NO citation | hallucination |
|---|---|---|---|---|
| naive (one line) | 100% | 94% | **20%** | 0% |
| **concise (shipped)** | 91% | 97% | **0%** | 0% |
| strict (a page of rules) | 87% | 97% | 2% | 0% |

**Read that table twice.** Hallucination is 0% everywhere — even with the lazy prompt. The
*schema* prevents it, not the instructions. And the naive prompt's 100% is a trap: a fifth
of its answers cite nothing, and an uncited answer cannot survive an auditor.

Longer prompts made this model **worse**, every time.

## New words

**Embedding** — a list of numbers representing meaning. Similar meaning → similar numbers.
Titan V2 gives 1024 numbers per chunk.

**Cosine similarity** — how close two embeddings point in the same direction. Because our
vectors are length 1, this is just a dot product: multiply and add.

```
question ─▶ embed ─▶ [0.02, -0.31, 0.88, ...]
                            ↓ compare to every chunk
                     highest score wins
```

**Chunk** — a piece of a document, embedded and stored. Section-aware means one heading =
one chunk.

**Recall** — of the answers that exist, how many did we find?

**MRR** (Mean Reciprocal Rank) — was the right answer at position 1, or position 5? Recall
says *did we find it*; MRR says *how near the top*.

**BM25** — classic keyword scoring. Rewards rare words, penalises long documents.

**Golden set** — questions with known correct answers, used to score changes.

**Hallucination** — the model states something the source does not say.

**Tool schema** — a JSON shape the model must fill in. Ours makes `answerable` a **required
boolean**, so the model must decide *before* it writes any words.

## Technical detail

- Embeddings: `amazon.titan-embed-text-v2:0`.
- Index: a numpy `.npy` file, 164 KB, 41 chunks. **No vector database.** At this size a dot
  product beats a service you have to run, and the ADR records the corpus size where that
  stops being true.
- BM25 tokeniser keeps `sc-28` and `aes-256` intact instead of splitting on the hyphen.
- Answers go through a Bedrock tool call with `toolChoice` forced, so the model cannot
  reply with free text.

## Ask yourself

1. Why write the 45 questions before writing the retriever?
2. Hallucination was 0% under every prompt. So what actually stops it?
3. Why did hybrid retrieval lose even though BM25 scored 100% on exact matches?

---

# Week 3 — multiple agents, and a human who can walk away

## What we built

```
retrieve ─▶ draft ─▶ verify ─▶ score confidence ─▶ ┬─ high  ─▶ auto-answer
                       ↑           ↓                └─ low   ─▶ park for a human
                       └── revise ─┘  (max 2 times)
```

- A **separate verifier agent** — a second model call whose only job is checking.
- A confidence score computed in Python.
- A real pause for human review, using LangGraph `interrupt()`.
- State saved to disk, so the process can die and resume.

## Why

Asking the same model "are you sure?" re-runs the pass that made the mistake. The verifier
gets a different job: for each claim, produce the **exact sentence** from the source. Then
Python — not a model — checks that sentence really appears in the document.

That last step cannot be talked out of.

## The numbers

**A 50-question run, end to end**

```
38 of 50 auto-answered, every one cited
12 flagged for a human
44 seconds
$0.008
```

Of the 12 flagged, **6 are correct refusals** — SOC 2, FedRAMP, HIPAA, bug bounty, cyber
insurance twice.

**Confidence — mine vs the model's own**

| Source | marked "high" | wrong | precision |
|---|---|---|---|
| **Our computed score** | 31 | **0** | **100%** |
| The model's self-report | 36 | 3 | 92% |

The model said 36 answers were high-confidence and was wrong on 3. Our score marked 31 and
was wrong on none — it moved those 3 to where a human catches them.

**Why:** a model's confidence comes from the same pass that produced the answer. It is not
independent evidence about it. We use it as the weakest tiebreak only.

**Durability — proven, not assumed**

```
process A: answers 3 questions, then SIGKILLs itself
process B: reads back 2 finished, 1 parked at ('human_review',)
           input tokens already spent: 1173
           resume it ─▶ still 1173
```

Nothing re-ran. Nothing was re-paid for. **That unchanged number is the entire reason to
adopt a framework.**

**Concurrency — measured, not guessed**

| parallel questions | time for 50 |
|---|---|
| 4 | 17.2 s |
| 20 | 15.7 s |
| 50 | 10.7 s |

Zero throttling, zero errors. The plan predicted Bedrock would throttle. It did not.
Default set to 20, at the knee of the curve.

**The verifier is not a clear win**

| | change |
|---|---|
| Answerable accuracy | **−4 points** |
| Token cost | **2×** |
| Citation precision | +2 points |

Shipped anyway, with the ADR saying the case is unproven. It guards against a failure the
eval set cannot see: an answer that quietly drifts to a different subject.

## New words

**LangGraph** — a library for building the flow above as a graph of nodes. We adopted it
for one feature: durable state.

**Checkpoint** — the saved state of a run at one moment. Ours go to SQLite locally,
DynamoDB on AWS.

**Interrupt** — LangGraph stops the graph mid-run and waits. The process can exit. Later,
`Command(resume=...)` continues from exactly that node.

**Thread id** — the key a checkpoint is stored under. Ours is `{job_id}:{question_id}` —
see the bug section for why that colon matters a lot.

**Reflection loop** — model sees its own mistake and retries. Ours is capped at 2. Without
a cap, a model that cannot fix something will burn tokens forever.

## Technical detail

- `StateGraph` with a `QuestionState` TypedDict. `MAX_REVISIONS = 2`.
- The verifier's win came from changing the **schema** (one quote per claim, checked in
  Python) — not from improving the prompt. Adversarial test cases went 2/4 → 4/4.
- Confidence floors: no citation, or verifier failed, forces low regardless of anything
  else.

## Ask yourself

1. Why is a second model call better than asking the first one "are you sure"?
2. Why don't we trust the model's own confidence number?
3. What exactly did the `SIGKILL` test prove?

---

# Week 4 — real documents, and a real control catalogue

## What we built

```
read PDFs ─▶ parse ─▶ write markdown ─▶ build index
                   ↘ document catalogue (which method worked, per file)
```

- A pipeline that turns real public policy PDFs into clean markdown.
- A **quality gate** that refuses documents it cannot parse properly.
- NIST 800-53 loaded from NIST's own machine-readable catalogue.
- A SOC 2 crosswalk.
- A mapper: answer → NIST control → SOC 2 criterion.

## Why

Hand-written test documents are too clean. Real PDFs have front matter, two-column layouts,
tables, and slide decks pretending to be policies.

**5 PDFs in, 3 usable out.** The 2 rejections are the point:

- one had no recoverable structure at all
- one was a **70-page PowerPoint** about incident response, which would otherwise have been
  indexed and cited to a customer as company policy

Refusing to ingest is a feature.

## The numbers

**Retrieval on real documents:** 92% recall (down from 97%), MRR 0.93 → 0.63.

Real sections are ~5× larger than hand-written ones, so the right chunk is found but ranks
lower.

**The control catalogue**

```
NIST SP 800-53 Rev 5, from NIST's own OSCAL JSON
  20 families
  324 base controls
  1,196 including enhancements
```

**The gap report**

| Report | Result |
|---|---|
| NIST controls with no policy behind them | **311 of 324** |
| SOC 2 criteria with nothing at all | **24 of 37** |
| `"Do you have an incident response plan?"` | → IR-04, IR-08 → CC7.3, CC7.4, CC7.5 |

That last row is the product claim: **answer once, serve two frameworks.**

**The mapper was 24% precise, and I published numbers based on it**

I eyeballed the top proposals, which only ever shows you the good ones. Scoring against a
set I labelled blind said 3 of every 4 mappings were wrong.

| threshold | precision | false positives | recall |
|---|---|---|---|
| 0.40 (shipped first) | 24% | 37 | 38% |
| **0.50 (corrected)** | **78%** | **2** | 22% |

Losing recall on purpose. **A missed mapping shows up as a gap someone fixes. A wrong one
shows up as coverage nobody rechecks.**

Then a second problem: raising the threshold changed nothing, because `INSERT OR REPLACE`
never deleted the 80 stale rows from the old run. Published figures were corrected from
274 → 311 and 15 → 24, with the wrong ones left visible next to them.

## New words

**OSCAL** — NIST's machine-readable format for control catalogues. Downloading their JSON
beats retyping 324 controls.

**Crosswalk** — a mapping between two frameworks. NIST IR-04 and SOC 2 CC7.3 are the same
requirement in different words.

**Precision vs recall**

```
precision = of what we proposed, how much was right
recall    = of what was right, how much did we propose
```

You trade one for the other. Which one you protect depends on which failure is worse.

**Dagster** — a data pipeline tool. Oversized for 5 PDFs on purpose, so I learn it. The
ADR says so plainly.

## Technical detail

- Heading detection is a **cascade**: text patterns → font size and weight → refuse. Which
  method won is recorded per document.
- Ontology lives in **SQLite**, not a graph database. Queries are two joins deep and the
  whole thing is one file.
- Every machine-proposed mapping stays **unconfirmed until a named person accepts it**. An
  embedding score is not a basis for telling an auditor a control is satisfied.

## Ask yourself

1. Why is refusing to ingest a document a feature?
2. Why deliberately accept lower recall in the mapper?
3. What was wrong with `INSERT OR REPLACE`?

---

# Week 5 — three ways in, one core

## What we built

```
graph ─▶ HTTP API    POST /questionnaires → 202 + job_id → poll → answers
      ↘ Python SDK   typed client, polling with backoff, named errors
      ↘ MCP server   ask from inside Claude or Cursor
```

Plus per-question telemetry: cost, latency, refusal rate.

## Why

A 200-question run takes ~4 minutes. That is longer than a load balancer will hold a
connection open.

So `POST` does not wait. It returns **202 Accepted** with a job id, and the work happens in
the background. This is the difference between a demo and something that survives a real
questionnaire.

None of the three interfaces owns any logic. All three call the same graph.

## The numbers

```
cost per question   $0.000305
latency median      2519 ms
latency p95         3289 ms
uncited answers     0
```

**Why p95 and not average?** An average hides the tail, and the tail is what someone
waiting on a 200-question run actually feels.

## New words

**202 Accepted** — HTTP for "I took your work, it is not done, here is where to check."

**Polling with backoff** — the client asks "done yet?", waiting longer between each ask.

**MCP** (Model Context Protocol) — lets Claude or Cursor call your tools directly. No
server to host.

**Telemetry** — recording what each run cost and where the time went. Deliberately stores
**numbers and ids only** — no question text, no answer text. Customer data does not belong
in an ops table.

## Technical detail

- FastAPI, with data routes on an `APIRouter` that carries the auth dependency.
- Refusal rate is tracked because a rising one means **the corpus stopped covering what
  people ask** — a product signal, not an error. Nothing throws when it happens.
- Uploads are capped: 2 MB, 500 rows, UTF-8 checked, duplicate ids rejected.

## Ask yourself

1. Why does `POST` return 202 instead of the answers?
2. Why does the telemetry table store no question text?

---

# Week 6 — deployed for real

## What we built

27 AWS resources, all in OpenTofu. Nothing created by hand.

```
API Gateway ─▶ Lambda (FastAPI via Mangum) ─▶ Bedrock
                     ↘ S3        index + ontology
                     ↘ DynamoDB  jobs + checkpoints
```

Plus a threat model, a CI pipeline, and a compliance self-assessment.

## Every service, and why it is there

| Service | Doing what | Idle cost |
|---|---|---|
| **Bedrock** | Nova Lite for drafting + verifying, Titan V2 for embeddings | $0 — per token |
| **Lambda** | The whole FastAPI app. 111 MB package | $0 |
| **API Gateway** | HTTPS front door, throttled 20 burst / 10 per sec | $0 |
| **S3** | Vector index + ontology. Versioned, encrypted, lifecycle rules | ~$0.01 |
| **DynamoDB** ×2 | Job state + LangGraph checkpoints. On-demand, TTL, PITR | $0 |
| **KMS** ×2 | Customer-managed keys with rotation — data, and logs | **$2.00** |
| **Secrets Manager** | The API key. Never in an env var, never in state as plaintext | ~$0.40 |
| **CloudWatch** | 2 encrypted log groups, 14-day retention, 3 alarms | ~$0 |
| **SNS** | Where the alarms go | $0 |
| **IAM** | One role, every action named individually | $0 |

**Total idle: ~$2.40/month.** Almost all of it the two KMS keys.

The budget is $5/month, which is why the stack goes down when nobody is looking at it.

## Why OpenTofu, not Terraform

Terraform moved to the BUSL licence in 2023. OpenTofu is the MPL fork under the Linux
Foundation. Same HCL, same providers, same commands. For a public repo anyone might clone,
the permissive licence is the safer default and costs nothing.

## Security decisions worth naming

- **No `s3:PutObject` for the Lambda.** The request path reads the index and never writes
  it, so a compromised API cannot alter the corpus its answers come from.
- **The bucket denies unencrypted uploads** and any request without TLS.
- **Access logs exclude request and response bodies.** They would contain customer data.
- **14-day log retention.** Infinite retention is both a cost leak and a data-retention
  problem.
- **TTL on checkpoints, 30 days.** An abandoned run should not hold questionnaire text
  forever.

## New words

**Infrastructure as Code (IaC)** — your servers described in files. `apply` builds them,
`destroy` removes them. Nothing clicked by hand.

**KMS CMK** — a customer-managed encryption key. Costs $1/month just to exist. This is why
the idle bill is not zero.

**Least privilege** — grant the exact action needed, nothing more. `bedrock:InvokeModel` on
two specific model ARNs, not on `*`.

**Mangum** — the adapter that lets a normal FastAPI app run inside Lambda.

**PITR** — point-in-time recovery. DynamoDB can restore to any second in the last 35 days.
Enabled — but **never tested**, which is written down as a gap.

## Ask yourself

1. Why is the idle cost $2.40 and not $0?
2. Why does the Lambda have no permission to write to S3?
3. What does `tofu destroy` protect you from?

---

# After week 6 — what testing it as a user found

Everything above was the plan. These came from actually using the deployed system, and
each one is a gap that a week of reading my own API docs had not surfaced.

| Gap | What was wrong | Fix |
|---|---|---|
| **No deliverable** | Could answer 17 questions, no way to return the finished sheet | `GET /questionnaires/{job}/export.csv` |
| **Looks broken** | `/docs` rendered every endpoint and could authenticate none | Declared the key as a real security scheme |
| **Unusable** | Driving it meant copying a job id between 5 collapsible sections | One HTML file at `/ui` |
| **Never self-audited** | The product audits compliance and had never audited itself | `COMPLIANCE.md` — 16 controls with evidence, 9 absent |

## The UI, and one security lesson

The page shows text a model wrote after reading documents we do not control.

```
policy PDF carries markup
  ↘ model repeats it in an answer
    ↘ page renders it with innerHTML
      ↘ script runs on the page holding the API key
```

Prompt injection → XSS → credential theft. Two defences:

1. Every value uses `textContent`, never `innerHTML`. A test greps the file for the HTML
   sinks and fails the build.
2. A **CSP** header with `connect-src 'self'` — if script ever did run, it still could not
   post the key anywhere.

**First stops execution. Second stops the data getting out.**

Honest weakness: `'unsafe-inline'` is required because the page has no build step. So the
policy is strong on exfiltration and weak on execution. That is in the ADR, not hidden.

## `COMPLIANCE.md` — the three real gaps

1. **No authentication worth the name.** A shared key gives no identity. The "confirmed by"
   field is free text anyone with the key can fill in. In a product whose output is an
   attestation, *who approved this* is not optional.
2. **Every tenant's text readable by one IAM role.** No per-tenant scoping.
3. **Backups never restored.** PITR is a setting, not a demonstrated capability.

---

# The bugs that taught me the most

Ten of 49. Each one in four lines.

### 1. Two customers with a question called `q1` shared an answer

`question_id` comes from a customer's CSV. I used it directly as the checkpoint key.
Everyone writes `q1`. Two tenants shared one checkpoint — the second read the first's data
then overwrote it.

**Lesson:** an id from a customer file is not a namespace key. Fixed with
`{job_id}:{question_id}`.

### 2. Three patches silently did nothing, and one shipped

The deployed API answered correctly then returned everything as `not_run`. Reading live
DynamoDB keys showed `e3`, not `{job}:e3` — the namespacing fix from three commits earlier
had never applied. The formatter had reformatted the file, so my string-replace found no
match. **A replace on a missing needle is a no-op, not an error.**

**Lesson:** an edit that does not apply looks exactly like one that did. Assert that every
replacement matched.

### 3. Raising the threshold changed nothing

`INSERT OR REPLACE` left 80 stale rows in place, still counting as coverage.

**Lesson:** that is an upsert, not a sync. A re-run must delete what the previous run
derived.

### 4. The CSV export could run code on the customer's machine

A cell starting `=` is a formula to Excel, evaluated on open. A question containing one
round-trips straight through.

**Lesson:** found by a security review, not a test. The export is the only thing the
customer opens.

### 5. SQLite is not the same SQLite on Lambda

Row values in an `IN` clause need SQLite 3.15+. My laptop has 3.50; Lambda ships older.

**Lesson:** no local test can catch this. The runtime's C libraries are not your machine's.

### 6. Two "read-only file system" errors from one assumption

Two components wrote under the repo root. Fine on a laptop, read-only at `/var/task`.

**Lesson:** I found the second only after fixing the first. One grep would have found both.

### 7. Six rounds of guessing at IAM permissions

I wrote the policy from what I expected each service to need.

**Lesson:** permission names come from error messages. Also — the IAM console's validator
rejected `apigateway:TagResource` as non-existent while AWS was enforcing it.

### 8. The deploy policy could build the stack and not take it down

`destroy` reported success on 25 of 27 and left a bucket and a role billing. Two
permissions existed only for that direction: `s3:DeleteObjectVersion` and
`iam:ListInstanceProfilesForRole`.

**Lesson:** half the lifecycle was untested, and it was the half that costs money. A
destroy that half-works reports success and the state file agrees with it.

### 9. The key-rotation procedure leaked the key

I rotated a key because it had been exposed — using a command that printed the new one to
the same place.

**Lesson:** a control can be correct and be defeated by how it is operated. Also, rotation
is not revocation here: the key is cached per Lambda container, so a warm one honours a
withdrawn key until it recycles.

### 10. A test that inspected the route table and tested nothing

FastAPI does not list `include_router` routes in `app.routes`. My test found no data routes
at all, so "none are unauthenticated" was vacuously true. It would have passed with auth
removed entirely.

**Lesson:** a test that inspects a framework's internals tests your understanding of the
framework, not your code.

---

# Four patterns across all 49

**1. Measure before you decide, and publish the loser.**
Hybrid retrieval, the verifier, and the strict prompt were all built and all lost. Each is
written up with its numbers instead of quietly deleted.

**2. A number in a README is a claim.**
Twice a published figure turned out wrong. Both times the document was amended, leaving the
wrong number visible beside the right one.

**3. The same mistake wears four costumes.**
Four times I wrote a check that matched the *shape* of something instead of its meaning:
counting empty sections, counting stale rows, asserting over an empty route table, and a
grep that tripped on its own comment.

**4. Deployment is a second product.**
15 of the 49 failures happened after the code was finished and working.

---

# Where everything lives

```
README.md              product + every measurement
CLAUDE.md              the rules this project is built under
MISTAKES.md            all 49 failures, in order
docs/STUDY-GUIDE.md    this file
docs/adr/              18 decisions, each with alternatives
docs/THREAT-MODEL.md   7 threats, attacker's view
docs/COMPLIANCE.md     the product audited against its own catalogue
docs/aws/DEPLOY.md     how to bring it up and take it down

src/rag/               chunking, embeddings, index, answer, verify
src/graph/             LangGraph nodes, state, confidence, batch
src/pipeline/          PDF parsing, quality gates
src/ontology/          NIST catalogue, mapper, SOC 2 crosswalk
src/api/               FastAPI, telemetry, the UI
src/aws/               DynamoDB checkpointer and job store
infra/                 27 OpenTofu resources
evals/                 golden sets and raw results
scripts/up.sh          deploy in one command
scripts/down.sh        destroy in one command
```

---

# The six sentences to remember

1. **The test set was written before the system**, so every change is a number.
2. **The schema stops hallucination**, not the prompt — longer prompts made it worse.
3. **A separate verifier, checked in Python**, because a model cannot witness its own work.
4. **Confidence is computed, not asked for** — the model's own guess was wrong 3 times out
   of 36.
5. **A wrong control mapping is worse than a missing one**, so precision beats recall here.
6. **Half the failures happened after the code worked.** Deployment is a second product.

---

# The question to be ready for

> "What broke while you were building this?"

There are 49 answers in `MISTAKES.md`. The strongest is bug 2 — a cross-tenant defect that
reached production because a patch silently did nothing, found by reading live database
keys rather than by any test I had written.
