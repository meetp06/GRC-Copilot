# ADR-0001: Record architecture decisions as ADRs

**Status:** Accepted
**Date:** 2026-08-31

## Context

I am building this project specifically to be able to answer *"why did you choose X over Y?"*
in interviews. I have no professional experience to draw on, so the project has to be the
evidence.

If I make decisions and only write them up at the end, I will forget the alternatives I
considered. The alternatives are the entire point — anyone can say "I used LangGraph."
Fewer people can say "I used LangGraph over CrewAI because I needed durable checkpoints for
a human approval step, and here's when CrewAI would have been the better call."

## Decision

Write one ADR per significant technology or design decision, in `docs/adr/`, numbered
sequentially, **on the same day the decision is made**. Use the template in `0000-template.md`.

A decision is "significant" if changing it later would require touching more than one module,
or if it costs money.

## Alternatives considered

### Write it all up at the end in the README
- Attractive: less overhead while building, one clean document.
- Rejected because: by week 6 I will not remember why I rejected Prefect in week 4. The
  reasoning decays faster than the code.
- **When it would be the better call:** a small project where the tech choices are obvious
  and nobody will ask about them.

### Comments in the code
- Attractive: lives next to what it describes, impossible to forget.
- Rejected because: comments explain *how this line works*, not *why this whole subsystem
  exists instead of a different one*. Wrong altitude. Also invisible to a non-technical reader.
- **When it would be the better call:** narrow, local decisions ("why this regex").

### A design doc in Notion / Google Docs
- Attractive: nicer to read, easy to share, good for diagrams.
- Rejected because: it drifts from the code and isn't versioned with it. An ADR changes in
  the same commit as the change it describes.
- **When it would be the better call:** a big up-front system design doc for stakeholders —
  which I will also write in week 7. ADRs and a design doc are complementary, not competing.

## Consequences

**Good:** ~10 ADRs by week 6 means I walk into interviews with a written, dated answer for
every "why" question. Also forces me to actually consider alternatives instead of picking
whatever the first tutorial used.

**Bad:** ~20-30 minutes of writing per decision. Real cost against a 20 hr/week budget. Risk
of over-documenting trivia — mitigated by the "significant" bar above.

## The interview answer

"I wrote an ADR for every major choice as I made it, so the alternatives I weighed are on
record rather than reconstructed after the fact."
