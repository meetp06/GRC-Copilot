# ADR-0013: The control ontology in SQLite, not a graph database

**Status:** Accepted
**Date:** 2026-09-07

## Context

Week 1 shipped `CONTROL_CATALOG` in `src/agent/tools.py`: eight NIST controls with a title
and a description, hardcoded. It answers one question — what is SC-28 — and that is genuinely
all week 1 needed.

It cannot answer any of the questions the product is actually for:

- Which controls does this company have no policy for?
- This answer cites a policy section — which controls does that section satisfy, and which
  other questionnaire questions does that make it serve?
- The buyer sent a SOC 2 questionnaire. Which of our NIST-mapped answers apply?

Those are questions about *relationships*, and a dictionary has none. That is the difference
between a lookup table and an ontology, and most projects that claim the second have built
the first.

## Decision

Five tables in SQLite at `data/ontology/ontology.sqlite`:

```
control_family ──< control ──< satisfies >── policy_section
                      │
                      └──< crosswalk (framework, criterion)
```

`control` is the full NIST SP 800-53 Rev 5.2.0 catalog loaded from NIST's own OSCAL JSON —
20 families, 324 base controls, 1,196 including enhancements. `satisfies` is the edge that
makes this an ontology rather than two lists.

## Alternatives considered

### Keep the hardcoded dictionary

- **Why it's attractive:** zero infrastructure, and eight controls covered every question in
  the week 2 golden set.
- **Why I did not pick it here:** the eight were chosen to match the corpus I wrote. Against
  real documents, 13 controls have policy behind them and 311 do not, and neither number is
  expressible in a dictionary.
- **When it would be the better call:** a demo that only ever looks up a control by id.

### Neo4j or another graph database

- **Why it's attractive:** this is genuinely a graph, and the query language matches the
  shape of the questions.
- **Why I did not pick it here:** every query I actually need is one or two joins. "SOC 2
  criterion → controls → policy sections" is two. The traversals are shallow and fixed, and
  the graph is small — 1,196 nodes and a few thousand edges. A server, a second query
  language, and a dependency for that would be infrastructure with nothing to do.
- **When it would be the better call:** deep or variable-length traversal (control → related
  control → shared evidence → other customer's control), or when relationships outnumber
  entities by an order of magnitude. If the crosswalk grows to a dozen frameworks all
  mapping to each other rather than through NIST, that flips.

### RDF and a triple store, with a real OWL ontology

- **Why it's attractive:** "ontology" in its strict sense — formal semantics, inference,
  interoperability with published compliance vocabularies.
- **Why I did not pick it here:** the inference is not needed. Nothing here derives new facts;
  the edges are asserted, by a machine and then confirmed by a person. Paying for reasoning
  nobody uses is the cost, and the tooling is unfamiliar to whoever maintains this next.
- **When it would be the better call:** publishing the ontology for others to extend, or
  needing subsumption reasoning across framework hierarchies.

## Two decisions inside the schema worth defending

**Machine-proposed edges land unconfirmed.** `satisfies` carries `confidence`, `method`, and
`confirmed_by`. Mapping 324 control statements against 41 policy sections by embedding takes
seconds and no analyst would do it by hand — but "an embedding scored 0.61" is not a basis
for telling an auditor a control is satisfied. So `confirmed_by` stays NULL until a named
person accepts the edge, and the gap report has a `--confirmed` flag that produces the longer,
honest list.

**Only base controls are mapped, not the 872 enhancements.** AC-2(1) is "automate account
management" — a stricter variant of AC-2. A policy section that satisfies AC-2 says nothing
about whether the automation exists. Proposing those edges would manufacture coverage, which
in this product means manufacturing a false attestation.

## Consequences

**Good:** gap analysis is one query and it is the thing a customer pays for. Against three
real university policies: **311 of 324 base controls have no policy section**. The SOC 2
crosswalk turns that into a readiness report — 24 of 37 criteria have no policy behind any
mapped control — and it means one answer serves two frameworks instead of being found again
per framework.

**Bad:** the crosswalk is hand-built. AICPA's official 800-53 mapping is not freely
redistributable, so this is roughly 40 criteria mapped by reading control statements on both
sides, every row marked `hand-built`. It is deliberately incomplete, and a production system
licenses the AICPA mapping or the Secure Controls Framework. A crosswalk presented as
authoritative when it is not is worse than none, because someone will rely on it in an audit.

The ontology is also a second store alongside the vector index, holding the same policy text
in a different shape. They can drift. `policy_section` is loaded from the same parsed markdown
the index is built from, but nothing yet enforces that they were built from the same run.

**Amendment, 2026-09-07: the mapping was measured, and it was bad.**

The paragraph that stood here said the quality claim rested on eyeballing the top proposals,
and that a labelled set should exist before the threshold was tuned further. That set now
exists (`evals/control_mapping_set.yaml`, 19 sections labelled blind to the mapper's output,
including 4 that satisfy no control). Scored against it, the shipped configuration was:

| threshold | precision | recall | F1 | false positives |
|---|---|---|---|---|
| **0.40 (shipped)** | **24%** | 38% | 0.30 | 37 |
| 0.45 | 42% | 31% | 0.36 | 14 |
| **0.50 (now)** | **78%** | 22% | 0.34 | 2 |
| 0.55 | 75% | 9% | 0.17 | 1 |

Three of every four mappings were wrong. Eyeballing the highest-scoring proposals showed me
the good ones and hid the rest, which is exactly what eyeballing does.

0.50 despite 0.45 having a marginally better F1, because F1 weights the two errors equally and
this product does not. A missed mapping appears in the gap report as a control with no policy,
which is conservative and gets fixed. A wrong mapping appears as coverage that does not exist,
and nobody looks at it again.

**The gap numbers in the original version of this ADR were wrong** — 274 of 324 controls
without policy, and 15 of 37 SOC 2 criteria. Those counted the bad edges as coverage. The
honest figures are **311 of 324** and **24 of 37**.

Fixing the threshold also exposed a second bug: `propose()` used `INSERT OR REPLACE` and never
deleted superseded proposals, so raising the threshold produced 14 edges while 80 stale ones
from the old run stayed in the table and kept counting. It now clears unconfirmed machine
proposals before inserting, and never deletes a human-confirmed edge.

**The limitation that remains:** the labels were written by the same author as the mapper,
blind to its output but not independent of it. Precision here is an upper bound, and should be
quoted with that caveat. A compliance analyst labelling the same sections is the next step.

## The interview answer

"Most people build a dictionary and call it an ontology. Mine has edges: control satisfied_by
policy section, control crosswalks_to SOC 2 criterion. That's what makes gap analysis one
query — 311 of 324 NIST controls have no policy behind them, and 24 of 37 SOC 2 criteria have
nothing at all. It's SQLite, not Neo4j, because every query I need is two joins over 1,196
nodes. And every machine-proposed mapping lands unconfirmed, because an embedding score isn't
a reason to tell an auditor a control is satisfied."
