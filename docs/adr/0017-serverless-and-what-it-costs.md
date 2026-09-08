# ADR-0017: Lambda and API Gateway, and the constraints that come with them

**Status:** Accepted
**Date:** 2026-09-07

## Context

A deployed portfolio project has one hard requirement that a production system does not: it
must cost nothing while nobody is looking at it. `docs/COST-GUARDRAILS.md` sets $5/month, and
the realistic traffic is a handful of requests when someone opens the link.

It also has a real requirement that a toy does not: the thing deployed has to be the same
system that was measured, or every number in the README becomes a claim about something else.

## Decision

```
API Gateway (HTTP API) ─▶ Lambda (FastAPI via Mangum) ─▶ Bedrock
                                  ↘ S3        index + ontology
                                  ↘ DynamoDB  jobs + checkpoints
```

27 resources. **~$2.40/month idle**, almost all of it two KMS keys at $1 each.

## Alternatives considered

### ECS Fargate or EC2

- **Why it's attractive:** no 15-minute limit, no cold starts, no package size ceiling, and
  the local code runs unchanged.
- **Why I did not pick it here:** both bill per hour whether or not a request arrives. The
  smallest sensible Fargate task is roughly $10/month to serve a page nobody is looking at.
- **When it would be the better call:** sustained traffic, or a workload that genuinely needs
  to run longer than fifteen minutes.

### API Gateway REST API rather than HTTP API

- **Why it's attractive:** request validators, API keys with usage plans, WAF integration.
- **Why I did not pick it here:** roughly three times the price per million requests, for
  features this does not use. Validation happens in FastAPI and the API key is checked in the
  application.
- **When it would be the better call:** when usage plans per customer are the product.

### Keeping SQLite on an EFS mount

- **Why it's attractive:** no storage port at all — the code would run unchanged.
- **Why I did not pick it here:** EFS bills per hour, and SQLite over NFS has well-known
  locking problems that appear under concurrency rather than in testing.

## The constraints, and what each one actually cost

**15-minute function timeout.** A question takes about 2.5 seconds, so 500 questions is
roughly 20 minutes — over the limit. The API caps an upload at 500 questions and the function
timeout is set to 300 seconds, which bounds a run well inside it. A genuinely large
questionnaire needs Step Functions or a queue, and that is not built.

**Background work does not survive the response.** On Lambda the runtime freezes the container
the moment the handler returns, so the daemon thread that runs a batch locally never resumes.
The work runs inline instead, which is why the row cap matters: it is the only thing keeping a
run inside the timeout.

**250 MB unzipped package.** Measured at 111 MB after excluding dagster, pdfplumber and mcp —
ingestion and developer tooling that has no business in a request path. Excluding them is the
right architecture rather than a size workaround, which is the only reason this was not a
container image.

**Read-only filesystem.** Two separate 500s after deploying, both writing to a path under the
repo root that is writable on a laptop and read-only in a package. The ontology now reads from
a copy in /tmp and telemetry writes to /tmp plus a structured log line, because /tmp does not
survive a cold start. MISTAKES entry 41.

**A different SQLite.** A query using row values in an IN clause needs SQLite 3.15+; it worked
on my 3.50 and failed on the runtime's older build with a syntax error. This class of bug
cannot be caught by any test running locally. MISTAKES entry 40.

**Cold start.** 3.5 seconds, of which about 3 is importing numpy, langgraph and pydantic. The
index download from S3 adds to the first request only, since /tmp persists on a warm
container. Provisioned concurrency would remove it and would bill per hour, which defeats the
point.

## Consequences

**Good:** the deployed system is the measured system. `src/api/main.py` is not a variant — the
same routes, the same graph, the same prompts. Storage is selected in one place from one
environment variable. And a paused questionnaire resumed in a Lambda container that had
replaced the one that paused it, which is the strongest version of the week 3 durability claim.

**Bad:** the DynamoDB checkpointer is code I wrote, not a library, so its bugs are mine. That
was deliberate — the alternative on PyPI is at 0.1.0 with a single release and would be holding
customer questionnaire text — but it is 250 lines of storage code with no production mileage.

**Unresolved, and it is in the threat model:** the API has a shared key and no per-tenant
authorisation, so anyone holding it can read and approve every tenant's answers. That is a
deployment blocker for a real multi-tenant service and is stated as one.

**CI does not deploy.** Applying from a pipeline needs a GitHub OIDC provider and a role, and
a pipeline that can deploy is a pipeline whose credentials can deploy. The workflow runs
`tofu validate` and `tfsec` on every pull request and stops there; `apply` is run by hand.

## What deploying actually cost in time

Six rounds of apply-fail-widen-IAM, because I wrote the deployment policy from what I expected
each service to need rather than from what it asked for — the same lesson as MISTAKES entry 4,
from week 1. Then four bugs that could only appear in production. The infrastructure was the
easy half; making the application run somewhere other than a laptop was the rest.

## The interview answer

"Lambda and API Gateway because idle cost had to be near zero — it's about $2.40 a month and
that's almost entirely two KMS keys. The interesting parts were the constraints: the 15-minute
ceiling meant capping a questionnaire at 500 questions, background threads don't survive the
response so batch work runs inline, and two separate bugs were writing to paths that are
read-only in a Lambda package. One bug could only ever appear in production — a SQL syntax that
needs a newer SQLite than the runtime ships."
