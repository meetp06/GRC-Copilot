# CLAUDE.md

Instructions for Claude Code working in this repository. Read this before doing anything.

## What this project is

GRC Copilot — a multi-agent system that automates security questionnaire responses.
See `README.md` for the product, `docs/ROADMAP.md` for the six-week plan.

## Who I am and why this matters

I am Meet Patel. I am building this to get hired as a Forward Deployed Engineer / AI
Engineer. I have a Master's in Data Science and no full-time professional experience yet.

**This project is my evidence.** In interviews I will be asked:

- "Why did you choose X over Y?"
- "What broke while you were building this?"
- "Walk me through how this works."

If you write the code and I don't understand it, the project is worthless to me. A working
repo I cannot explain is worse than a half-finished one I can.

## Ground rules — follow these on every task

### 1. Explain before you write

Before writing any non-trivial code, tell me:
- what you're about to build and why
- what the alternative approaches are
- which one you'd pick and what it trades off

Then wait for me to agree. Don't produce a plan and immediately implement it in the same
turn.

### 2. Never write these files for me

- `MISTAKES.md` — I write every entry myself, in my own words
- `docs/adr/*.md` — I write the ADRs. You may tell me *what decision needs recording* and
  what the alternatives are. I write the prose.
- Blog posts, the demo script, my interview answers

You can review what I write and tell me if the reasoning is weak. Don't replace it.

### 3. Small diffs

One concern per change. If a task touches more than about three files, stop and propose
splitting it. I need to be able to read every diff.

### 4. Teach while building

When you use something I haven't seen before — a library, an AWS service, a pattern —
explain it in two or three sentences inline. Assume I know Python and SQL well, and that
I am new to: LangGraph, production RAG, Terraform, AWS IAM detail, Dagster.

### 5. Make me answer things

At natural checkpoints, ask me a question about what we just built instead of moving on.
If I can't answer, we go back. I would rather move slowly.

### 6. Stop and ask before

- adding any dependency (say why, and what it replaces)
- creating any AWS resource that costs money when idle
- changing anything under `infra/`
- writing more than ~150 lines in one go

## Cost rules — non-negotiable

- Target: under **$5/month** total
- **Never create an OpenSearch Serverless (Classic) collection.** It bills roughly $350/month
  even when idle. If a task seems to need it, stop and tell me.
- Use the cheapest Bedrock model for the dev loop. Only route hard steps to a stronger model.
- No always-on compute before week 6. Lambda and S3 only.
- Before creating any AWS resource, tell me what it costs at rest and under my usage.
- If you see a way to test something without calling the model, prefer it.

## Security rules

This is a compliance product. Sloppy security here is embarrassing in a way it wouldn't be
elsewhere.

- Secrets come from environment variables, never literals. `.env` is gitignored — keep it
  that way.
- Never log full prompts or full documents at INFO level. They contain customer data by
  design.
- IAM policies are least-privilege. If you need a new permission, name the exact action.
- Validate anything that reaches a tool call. Assume questionnaire input is hostile —
  prompt injection through an uploaded document is a real threat for this product.
- No `pickle`, no `eval`, no shell interpolation of user input.

## Code conventions

- Python 3.11+, type hints on function signatures
- `ruff` for lint and format (config in `.pre-commit-config.yaml`)
- Docstrings explain *why*, not *what*. The code says what.
- Tests in `tests/`, pytest, no network calls in unit tests — mock Bedrock
- Module layout: `src/agent/`, `src/rag/`, `src/api/`, `src/pipeline/`

## Definition of done for any task

1. It runs
2. There's a test, or a documented reason there isn't
3. I can explain it out loud
4. If it was a real decision, an ADR exists (written by me)
5. If something broke on the way, it's in `MISTAKES.md` (written by me)

## Where things are

```
README.md                  product + status
CLAUDE.md                  this file
MISTAKES.md                my running bug log
docs/ROADMAP.md            the whole six-week plan
docs/weeks/WEEK*.md        detailed plan per week
docs/TECH-CHOICES.md       every technology, its alternatives, when to pick each
docs/MISTAKES-TO-HUNT.md   failures to trigger on purpose, per week
docs/INTERVIEW-PREP.md     the story, the question bank
docs/COST-GUARDRAILS.md    AWS cost safety
docs/adr/                  architecture decision records
src/                       code
data/policies/             sample policy corpus
```

## Current state

Week 1 complete: hand-written agent loop over Bedrock, two naive tools, four ADRs.
Next: `docs/weeks/WEEK2.md`.

Check the status table in `README.md` — I keep it current.
