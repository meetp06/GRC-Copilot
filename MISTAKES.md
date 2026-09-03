# Mistakes Log

Every bug, wrong turn, and surprise. Written down **the day it happens**, while the details
are fresh.

This file exists because "tell me about something that broke while you were building this"
is the question I could not answer before. Now I can.

## Format

### YYYY-MM-DD — Short title
**What happened:** the symptom I actually saw.
**Why:** the real root cause, not the first guess.
**Fix:** what I changed.
**Lesson:** what I'd do differently, or what I now check by default.

---

### 2026-XX-XX — (template, delete me)
**What happened:** The agent kept calling `search_policies` with the same query and never
stopped. Burned ~40k tokens before I killed it.
**Why:** No step limit. The model got a bad search result, didn't know what else to do, and
retried forever. Classic unbounded agent loop.
**Fix:** Added `MAX_AGENT_STEPS` to the loop, plus a repeated-tool-call detector that breaks
out if the same tool is called with identical args twice in a row.
**Lesson:** Never write an agent loop without a step cap. This is the #1 way people get a
surprise LLM bill. It's also OWASP LLM10 (Unbounded Consumption).
