# ADR-0003: Hand-write the agent loop in week 1, adopt LangGraph in week 3

**Status:** Accepted
**Date:** 2026-08-31

## Context

The end state (week 3+) is a LangGraph multi-agent system: supervisor, retriever, drafter,
citation-verifier, and a reflection step, with checkpointing and a human approval gate.

I could start there immediately. But a stated goal of this project is to be able to explain
*what the framework is actually doing*. Interviewers ask "how does an agent loop work" and
"how do you stop an agent from looping forever." If my only experience is calling
`create_agent()`, I cannot answer either question.

## Decision

Week 1: implement the agent loop by hand in `src/agent/loop.py` — a plain `while` loop over
the Bedrock `converse` API with tool dispatch, a step cap, a token budget, and a
repeated-call detector. No agent framework.

Week 3: port that same behaviour into a LangGraph `StateGraph`, keeping the tools unchanged,
and write ADR-000X comparing the two.

## Alternatives considered

### Start with LangGraph in week 1
- Attractive: no throwaway work, get to the real architecture faster, ~10 hours saved.
- Rejected because: the loop is ~120 lines. Writing it costs one evening and buys permanent
  understanding of state, tool-result message shape, stop reasons, and where cost actually
  accumulates. When LangGraph misbehaves in week 3, I'll know whether the bug is mine or the
  framework's.
- **When it would be the better call:** a deadline-driven work project where shipping beats
  learning. That is explicitly not this project.

### Start with a high-level framework (CrewAI, Bedrock Agents, Strands)
- Attractive: fastest path to a working multi-agent demo; Bedrock Agents and AgentCore even
  run the loop server-side as a managed "harness."
- Rejected because: these abstract away the most instructive part, and the managed options
  cost money per invocation. AgentCore stays on the week-8 stretch list as a deployment
  target once the agent already exists.
- **When it would be the better call:** shipping a role-delegation product quickly, or when
  an ops team needs a managed runtime rather than self-hosted code.

### Never adopt a framework — hand-roll everything
- Attractive: total control, zero dependency risk, no version churn.
- Rejected because: I would end up rebuilding checkpointing, interrupt/resume, and streaming
  badly. Human-in-the-loop approval on durable state is the feature that makes this product
  credible, and LangGraph gives it to me directly. Also, the JD names LangGraph.
- **When it would be the better call:** a simple single-tool prompt wrapper with no state.

## Consequences

**Good:** I can explain the loop from first principles, and I'll have a real before/after
comparison to talk about. Tools written in week 1 carry forward unchanged.

**Bad:** ~6-8 hours of work that gets replaced in week 3. The hand-rolled loop has no
persistence, so a crash loses the run — acceptable for week 1, and precisely the gap that
motivates the checkpointer later.

## The interview answer

"I wrote the reason-act-observe loop by hand first so I understood what the framework
abstracts — then moved to LangGraph specifically when I needed durable state and an
interrupt for human approval, which is where a hand-rolled loop stops being enough."
