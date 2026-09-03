# Week 5 — API, SDK, MCP, observability (target: 20 hours)

**Milestone:** someone who has never seen the code can use this — over HTTP, from a Python
client, or from inside Claude or Cursor. And you can see exactly what every run cost and
where the time went.

---

## Day 1-2 — FastAPI (6h)

```
POST   /questionnaires              upload a questionnaire, returns job_id
GET    /questionnaires/{id}         status + progress
GET    /questionnaires/{id}/answers all answers with citations and confidence
GET    /reviews                     answers awaiting human review
POST   /reviews/{id}/approve        approve, optionally with an edit
POST   /reviews/{id}/reject         reject with a reason
GET    /controls/{id}               ontology lookup
GET    /gaps                        controls with no supporting policy
GET    /health
```

**The async problem is the interesting part.** A 200-question run takes minutes. An HTTP
request that blocks for four minutes will be killed by a load balancer. So:

- `POST` returns `202 Accepted` with a `job_id` immediately
- Work happens in the background
- Client polls status, or you add webhooks

Design decisions to make consciously and record:
- Where does background work run? (Start: FastAPI `BackgroundTasks`. Note the limitation —
  it dies with the process. Week 6 moves it to a queue.)
- Idempotency: what if the same questionnaire is uploaded twice?
- Pagination on the answers endpoint
- Error shape: consistent JSON errors, not raw stack traces

Pydantic models for every request and response. This gives you OpenAPI docs for free — and
those docs *are* the "documentation" bullet, partly.

Auth: a simple API key checked from Secrets Manager. Not real auth, and say so in the
limitations section. Real would be OAuth with per-tenant scoping.

## Day 3 — Python SDK (4h)

A thin client so the API is pleasant to use:

```python
from grc_copilot import Client

client = Client(api_key=..., base_url=...)
job = client.submit_questionnaire("vendor_sig.xlsx")
job.wait()                              # polls with backoff
for answer in job.answers():
    print(answer.text, answer.citation, answer.confidence)

for review in client.pending_reviews():
    review.approve(edited_text="...")
```

What makes an SDK good rather than a wrapper:
- Retries with exponential backoff, handled for the caller
- Typed responses, not raw dicts
- Real exception classes (`RateLimitError`, `ValidationError`), not `raise Exception`
- Sensible defaults, everything overridable
- A `wait()` that polls intelligently instead of hammering

Package it, publish to **TestPyPI**. Write the README with a working example as the first
thing on the page.

## Day 4 — MCP server (4h)

Expose the same capability as MCP tools so it works from inside Claude Desktop, Claude Code,
or Cursor. Use **FastMCP** — it's the maintained path.

Tools to expose:
- `answer_security_question(question)` — single question, returns answer + citation
- `search_policies(query)` — raw retrieval
- `get_control_info(control_id)` — ontology lookup
- `list_gaps()` — unmapped controls

**Why this matters for the product, not just the resume:** a compliance analyst lives in a
spreadsheet and a chat window, not in your web app. Meeting them where they are is the
forward-deployed instinct. Say it that way.

Test it by actually connecting it to Claude Desktop and using it. Screenshot that for the
demo — it's a strong visual.

## Day 5 — Observability (4h)

Wire in **Langfuse** (self-hosted free tier or cloud). Trace every LLM call with:

- token counts and cost, per call and per questionnaire
- latency per node in the graph
- which retrieval chunks fed which answer
- the full trace of a reflection loop when the verifier rejects a draft

Then answer these from the dashboard, and put the answers in the README:

1. What does one 50-question questionnaire cost, end to end?
2. Which node is slowest?
3. Which node burns the most tokens?
4. How often does the verifier reject a first draft?
5. What's the p95 latency per question?

**These numbers are your interview material.** "It costs about eleven cents and four minutes
per fifty-question questionnaire, and the verifier rejects roughly one first draft in six"
is a sentence almost no candidate can say about their own project.

Add structured logging (`structlog`), with a request ID threaded through. **Never log full
document contents or full prompts at INFO** — customer data by design.

---

## Break it on purpose

- **Return the job synchronously.** Watch a long run time out. That's your async justification.
- **Submit the same questionnaire twice.** No idempotency key means duplicate work and
  double cost.
- **Kill the API mid-job.** `BackgroundTasks` loses the run. That's the week 6 queue
  justification, demonstrated.
- **Send a malformed spreadsheet.** Does it return a clear 400 or a 500 with a stack trace?
- **Hammer the endpoint.** No rate limiting means one caller can spend your whole Bedrock
  budget.

---

## Definition of done

- [ ] FastAPI running locally, OpenAPI docs readable
- [ ] Async job submission with polling
- [ ] SDK on TestPyPI with a README that works when copy-pasted
- [ ] MCP server verified working inside Claude Desktop (screenshot taken)
- [ ] Langfuse traces with cost per questionnaire
- [ ] The five observability numbers above, written into the README
- [ ] Structured logging, no sensitive data at INFO
- [ ] 3 new ADRs (async design, MCP transport, observability stack)

## If you fall behind

Cut the SDK. Keep the API, MCP, and observability — the cost numbers are worth more in an
interview than a client library.

## Interview answers you'll own after this week

- "How do you design an API for an operation that takes four minutes?"
- "What does your system cost to run?"
- "What makes an SDK good instead of just a wrapper?"
- "How would a compliance analyst actually use this day to day?"
