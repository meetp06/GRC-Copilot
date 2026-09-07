# ADR-0015: Three interfaces over one core

**Status:** Accepted
**Date:** 2026-09-07

## Context

The graph answers questions. Week 5 had to make that usable by someone who has never seen the
code — and "someone" is three different people with three different habits:

- an engineer integrating it, who wants HTTP
- an analyst writing a script, who wants a Python object
- an analyst filling in a questionnaire, who is already in a chat window

## Decision

```
graph (src/graph) ─▶ HTTP API   ─▶ curl, any language, any client
                  ↘ Python SDK  ─▶ scripts and notebooks (wraps HTTP)
                  ↘ MCP server  ─▶ Claude Desktop, Cursor (calls the graph directly)
```

The SDK wraps the API. The MCP server does **not** — it calls the graph in-process.

## The asymmetry, and why it is deliberate

The SDK goes over HTTP because its callers are already running a server, and because a client
that shares a process with the server cannot be tested against a real one.

The MCP server calls the graph directly because its setup story is "clone the repo, point
Claude at it". Requiring a running API first would double the setup and put a network hop
inside a chat turn. The cost is a second vector index in memory and no shared job state — an
MCP session cannot see the review queue. That is an acceptable trade for a tool used
interactively on one question at a time, and it is the thing to revisit if MCP ever needs to
submit a whole questionnaire.

## Alternatives considered

### API only

- **Why it's attractive:** one surface, one thing to document and version.
- **Why I did not pick it here:** every caller reimplements polling with backoff, and gets it
  wrong in the same three ways. And MCP is the interface that makes this demonstrable in a
  conversation rather than a browser.
- **When it would be the better call:** if the only consumer were a front end.

### SDK only, no HTTP

- **Why it's attractive:** simpler, and the SDK is nicer to use.
- **Why I did not pick it here:** it locks every integration into Python.

### MCP only

- **Why it's attractive:** it is the most striking demo, and the least common thing to have
  built.
- **Why I did not pick it here:** a questionnaire is a batch job with a review queue. That is
  not chat-shaped.

## Consequences

**Good:** the core is untouched by any of them. The graph does not know whether it was called
by uvicorn, a script, or Claude, which is why all three could be added in one day.

The MCP server is the demo: an analyst asks a question in the chat window they are already in,
and gets an answer with a citation, the NIST controls it satisfies, and the SOC 2 criteria
those serve. Few candidates have built one.

**Bad:** three surfaces to keep in step. A field added to the API's `Answer` has to be added
to the SDK's dataclass and considered for the MCP tool's JSON. Nothing enforces that today,
and the first drift will be a field that exists in two of the three.

The MCP server also holds its own index and its own graph, so a machine running both the API
and the MCP server has the corpus in memory twice.

## The interview answer

"One core, three ways in. The SDK wraps the HTTP API because its callers already have a server
running. The MCP server deliberately doesn't — it calls the graph in-process, so setup is
'clone the repo and point Claude at it' rather than 'run a server first'. The trade is that an
MCP session can't see the review queue, which is fine for one-question-at-a-time use and is
the thing I'd change if it needed to submit whole questionnaires."
