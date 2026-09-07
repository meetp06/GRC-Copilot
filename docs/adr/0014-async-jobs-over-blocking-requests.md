# ADR-0014: 202 Accepted and a job id, not a blocking request

**Status:** Accepted
**Date:** 2026-09-07

## Context

Answering a question takes about 2.5 seconds — 41 chunks retrieved, one draft call, one
verify call. A 50-question questionnaire takes about a minute. A 200-question one, which is
the realistic size, takes four.

An HTTP request that holds a connection open for four minutes gets killed. Load balancers
default to 60 seconds, API Gateway caps at 29, and a browser fetch that waits four minutes
looks broken whether or not it is.

## Decision

```
POST /questionnaires -> 202 Accepted + job_id     (returns immediately)
                     ↘ background thread runs the batch
GET  /questionnaires/{id} -> progress             (client polls)
```

202 rather than 200: the work has been *accepted*, not done, and the status code should not
claim otherwise. The response carries the `status_url` so a client does not have to construct
it.

## Alternatives considered

### Block until done

- **Why it's attractive:** one request, one response, no polling, no job table.
- **Why I did not pick it here:** it works until the questionnaire is realistic, then breaks
  in a way that looks like a server fault. The failure is also expensive — the work completes
  and the answer is thrown away with the connection.
- **When it would be the better call:** a single-question endpoint, which is worth adding.

### A real queue — SQS, Celery, RQ

- **Why it's attractive:** the correct shape. Work survives a process restart, retries are
  built in, and workers scale separately from the API.
- **Why I did not pick it here:** a broker is infrastructure running before week 6, and the
  cost rules forbid always-on compute until then. A thread is enough for one process.
- **When it would be the better call:** the moment there is more than one API process, or the
  moment a lost job matters. Both are true in production; neither is true today.

### Webhooks instead of polling

- **Why it's attractive:** no wasted requests, and the client learns immediately.
- **Why I did not pick it here:** it needs the client to run a reachable HTTP endpoint, which
  turns a five-line script into a deployment. Polling with backoff costs a handful of requests
  for a four-minute job.
- **When it would be the better call:** an integration partner who already has an endpoint.

## Consequences

**Good:** a 200-question upload returns in milliseconds. Progress is observable while the run
is in flight — `completed`, `needs_review` and `failed` update per question, so a client can
show a bar rather than a spinner. One question failing does not fail the job; a batch of 200
that died on question 3 would have wasted the other 197.

**Bad, and this is the real cost:** the work lives in a thread inside the API process. If that
process restarts mid-run, the job stays `running` forever and no one is told. The individual
*questions* survive — they are checkpointed per ADR-0011, so a re-submit skips them — but the
job row is a lie until someone looks. A reaper that fails jobs with no progress, or a real
queue, is the fix, and neither exists.

Job state is a separate SQLite store from the LangGraph checkpointer because they answer
different questions: the checkpointer knows where one *question* is in the graph, the job
table knows where one *questionnaire* is as a unit of work. Sharing them would couple the API
to a library's internal schema.

## The interview answer

"A 200-question run takes four minutes, and a load balancer kills anything past 60 seconds, so
POST returns 202 with a job id and the work happens in the background. The honest weakness is
that the worker is a thread in the API process — if it restarts, the job row says running
forever. The questions themselves are checkpointed so nothing is re-paid for, but the job
status lies, and fixing that properly means a queue, which is week 6 infrastructure."
