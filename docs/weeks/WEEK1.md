# Week 1 — Raw agent loop (target: 20 hours)

**Milestone:** type a security questionnaire question in the terminal, get back a JSON answer
with a citation and a control ID, produced by an agent that decided on its own which tools to
call.

No framework. No cloud infrastructure. No vector database. Just Python, boto3, and Bedrock.

---

## Day 1 — Account and safety rails (3h)

Do this before writing any code. This is the step people skip and regret.

- [ ] Create the AWS account (or use your existing one)
- [ ] **Set an AWS Budgets alarm at $1** with email notification. Non-negotiable.
- [ ] Create an IAM user (not root) with only: `bedrock:ListFoundationModels`,
      `bedrock:InvokeModel`, `bedrock:Converse`. Least privilege from day one — you'll cite
      this in week 6.
- [ ] `aws configure --profile grc-copilot`
- [ ] In the Bedrock console → **Model access**, request access to a cheap model
      (Amazon Nova Micro or Lite, or Claude Haiku). Approval is usually instant.
- [ ] Confirm root account has MFA on

**Why this first:** Bedrock has no free token allowance. Every call costs money from your
first line of code. The budget alarm is your seatbelt.

## Day 1 — Repo setup (2h)

- [ ] `git init`, push to GitHub (private for now)
- [ ] `python -m venv .venv && source .venv/bin/activate`
- [ ] `pip install -r requirements.txt`
- [ ] `pre-commit install` — this is what stops you committing a `.env` file
- [ ] `cp .env.example .env` and fill it in
- [ ] Confirm `.env` is gitignored: `git check-ignore .env` should print `.env`

## Day 2 — Verify Bedrock access (2h)

- [ ] `python scripts/check_bedrock.py`
- [ ] Copy the cheapest working model ID into `.env` as `BEDROCK_MODEL_ID`
- [ ] Re-run until the smoke test prints `OK -> 'ok'`

**Expect to get stuck here.** `AccessDeniedException` usually means model access isn't
granted yet, or you're in the wrong region. Log whatever bites you in `MISTAKES.md` — this
is exactly the kind of thing an interviewer means by "what went wrong."

## Day 2-3 — Read and run the loop (4h)

- [ ] Read `src/agent/loop.py` top to bottom before running it. Every line should make sense.
- [ ] `python -m src.agent.loop "Do you encrypt customer data at rest?"`
- [ ] Watch the step-by-step tool calls print out
- [ ] Try these and note what happens to step count and token usage:
  - `"Do you enforce MFA for employee access to production?"`
  - `"How quickly do you remediate critical vulnerabilities?"`
  - `"Do you have a SOC 2 Type II report?"` ← no evidence exists; does it correctly say so?
  - `"What is your data retention period?"`

**Checkpoint question to answer in your own words:** why do tool results get appended as a
`user` message and not an `assistant` message?

## Day 3-4 — Break it on purpose (5h)

The point of week 1 is not working code. It's understanding failure. Do each of these,
watch it break, then write it up in `MISTAKES.md`.

- [ ] **Remove the step cap.** Set `MAX_AGENT_STEPS=100`, then ask something the policies
      don't cover. Watch how many steps and tokens it burns. Put the cap back.
- [ ] **Remove the repeated-call guard** (comment out the `signature == last_tool_call`
      branch). Ask a question with no good answer. Watch it call the same search forever.
- [ ] **Set `maxTokens` to 50** in `bedrock_client.converse`. See `stopReason: max_tokens`
      and a truncated, unparseable answer.
- [ ] **Break the tool description.** Change `search_policies`' description to just
      `"Searches things."` Notice the model calls it with worse queries. This is prompt
      engineering — the tool schema is part of your prompt.
- [ ] **Find a query keyword search fails on.** `"how fast do you patch severe flaws"`
      returns nothing, even though the vulnerability policy answers it exactly — no keyword
      overlaps. This single failure is the entire argument for embeddings in week 2. Write
      down three more queries that fail this way.

## Day 5 — Write it down (4h)

- [ ] Fill in `MISTAKES.md` with everything from days 2-4. Real entries, not the template.
- [ ] Write **ADR-0004** on your Bedrock model choice: which model ID you picked, what it
      costs per million tokens, what you rejected, when you'd switch to a stronger model.
- [ ] Update the README status table
- [ ] Commit with a real message and push

---

## Definition of done for week 1

- [ ] `python -m src.agent.loop "<question>"` returns valid JSON with a citation and control ID
- [ ] You can explain the loop out loud in under 2 minutes with no notes
- [ ] You can name three ways an agent loop can run away, and the guard for each
- [ ] `MISTAKES.md` has at least 4 real entries
- [ ] 4 ADRs exist (0001-0004)
- [ ] AWS spend for the week is under $1

## If you fall behind

Cut the "break it on purpose" day down to just the step-cap and the failed-keyword-search
experiments. Those two are the ones you'll actually be asked about. Never cut the ADRs or
`MISTAKES.md` — they are the deliverable, not the code.

## What week 2 fixes

Every limitation you hit this week:
- keyword search misses synonyms → embeddings + hybrid search + reranking
- JSON parsing is fragile → structured output via a tool call
- no way to know if answers are good → a 30-50 question golden eval set + Ragas
- context is one big blob → real chunking strategy
