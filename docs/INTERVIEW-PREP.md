# Interview Prep

The project only works if you can tell the story. Nobody reads a GitHub repo before an
interview — they listen to you talk for two minutes and decide whether you're interesting.

Practice these **out loud**. Reading them is not the same thing.

---

## The two-minute story

Structure: problem → why it's hard → what you built → what you learned.

> A company selling software to a large enterprise gets hit with a two-hundred-question
> security questionnaire before the deal closes. Someone spends two to four days copying
> answers out of policy documents, and the deal sits waiting.
>
> It looks like a search problem, but it isn't. Every answer needs a citation to a source
> document, because an auditor will check it. And a wrong answer isn't a bad search result —
> it's a false attestation to a customer. So the system has to know when it doesn't know.
>
> I built a multi-agent system on LangGraph. It retrieves from the company's own policies
> using hybrid search, drafts an answer, and then a separate verifier agent checks that every
> claim in the draft actually appears in the source text. It maps each answer to a NIST
> 800-53 control, scores confidence, and routes anything low-confidence to a human review
> queue with a durable checkpoint, so a run can pause for a day and resume.
>
> The part I'd point at first is the evaluation. I built a fifty-question golden set before I
> improved retrieval, including questions the corpus genuinely can't answer — because the
> most dangerous failure here is confidently inventing a policy. Every improvement after
> that is a number, not a guess. Hybrid search over dense-only moved context recall from X to
> Y, and the reranker didn't help enough to justify the latency, so I dropped it.
>
> A fifty-question questionnaire runs in about four minutes for about eleven cents, with
> roughly forty-seven auto-answered and three flagged for review.

Fill in the real numbers as you get them. **Numbers are the whole point** — they're what
separate this from a tutorial.

---

## "What went wrong?" — have four ready

This is the question you couldn't answer before. `MISTAKES.md` is where the material comes
from. Pick four with different flavors:

1. **A runaway cost/loop bug** — the unbounded agent loop. Symptom, root cause, the three
   guards you added, and the general lesson about bounding agent execution.
2. **A retrieval failure that changed the design** — the query where keyword search returned
   nothing despite the answer being right there. Led to hybrid search. Shows measurement
   driving design.
3. **Something about real-world data** — the scanned PDF that produced zero chunks silently,
   or the eval metrics dropping when you moved off clean markdown. Shows you've met messy
   data.
4. **A security finding** — prompt injection through an uploaded document. Shows you think
   adversarially about your own system.

For each, use the same shape: **what I saw → what it actually was → what I changed → what I
now do by default.** That last part is what makes it sound like experience rather than an
anecdote.

---

## Question bank

### On the agent system
- Walk me through your agent loop. *(You wrote it by hand — draw it.)*
- When do you actually need a framework instead of a while loop?
- How do you stop an agent from looping forever? *(Three guards, name them.)*
- Two agents disagree. What happens?
- How does a human get into the loop without blocking everything?

### On RAG
- How do you know your retrieval is any good?
- Why hybrid search instead of embeddings alone? *(The `SC-28` exact-token argument.)*
- How did you choose your chunk size? *(You measured. Give the numbers.)*
- How do you stop it hallucinating a policy that doesn't exist? *(Verifier node, unanswerable
  questions in the eval set, refusal accuracy as a metric.)*
- What did you try that didn't work?

### On architecture
- Why Bedrock over calling a provider directly?
- Why LangGraph over CrewAI?
- Why not a graph database for the ontology? *(And what would change your mind.)*
- What breaks first if this goes from ten customers to a thousand?
- What would you do differently starting over?

### On security
- How do you secure an LLM app that reads customer documents?
- Explain prompt injection. How do you defend against it? *(Be honest: mitigated, not
  solved. Nobody has solved it.)*
- How do you keep two customers' data apart?
- What's the worst thing that could happen if this system is wrong?

### On the product and the customer — **the FDE-specific ones**
- Who's the buyer? Who's the user? Are they the same person? *(Buyer: the startup's founder
  or head of security. User: a compliance analyst or a founder doing it themselves.)*
- How would you know if this is actually valuable?
- The customer says the answers aren't good enough. What do you do first? *(Look at their
  eval set, not their vibes — and if they don't have one, build one with them. That answer
  is very strong.)*
- How would you onboard a new customer's document corpus?
- What would you cut to ship in two weeks?

---

## Mapping to the job description

Have a specific artifact for each bullet — not a claim, a thing you can show.

| JD bullet | Your artifact |
|-----------|---------------|
| LLMs, RAG, prompt engineering | Hybrid retrieval + eval set with real metrics; tool schemas as prompts |
| Multi-agent, LangGraph | Supervisor + verifier + reflection graph; the hand-written loop it replaced |
| Secure cloud, AWS, Bedrock | Terraform, KMS, least-privilege IAM, threat model, `COMPLIANCE.md` |
| Data pipelines, ETL, catalogs, ontologies | Dagster assets with lineage; NIST↔SOC 2 crosswalk ontology |
| REST APIs and SDKs | FastAPI with async jobs, Python SDK on TestPyPI, MCP server |
| DevOps, CI/CD, secure coding | GitHub Actions with OIDC, security scanning, eval gate on regression |
| Documentation and stakeholder comms | 15+ ADRs, threat model, design doc, demo video, blog posts |

**On the GovCloud / IL5 bullet — be honest.** Say: *"I built to NIST 800-53 control patterns
in commercial AWS and documented the control-to-resource mapping. I haven't worked in
GovCloud or an IL5 environment — that needs an organizational sponsor. What I can show is
that I know what those controls require and how to implement them."* That's a strong answer.
Overclaiming to people who work in this field every day is fatal.

---

## Things to do that aren't code

**Start applying in week 3.** Not week 7. You'll have enough to talk about, and interviews
will tell you which parts of the project matter most. Waiting for "done" costs you two
months of pipeline and teaches you nothing.

**Talk to real people.** Message five people who do GRC or security compliance work — on
LinkedIn, in security Slack communities, at local meetups. Ask whether the problem is real
and how they handle it today. Two things happen: the product gets sharper, and you can open
an interview with *"I talked to six compliance analysts and the thing they actually hate is
X"*, which is exactly the forward-deployed instinct the role is testing for.

**Write in public.** Three posts on the genuinely interesting parts: building the eval set
before improving retrieval; the prompt injection threat model; what LangGraph actually bought
over the hand-written loop. Post them. This is how people find you.

**Rehearse the demo.** Three to four minutes: the problem, a live run, the human approval
moment, the cost trace. Record it. Watch it back — you'll hate it, and it'll be better the
second time.

---

## What good looks like at the end

You can sit down with a founder and say: here's the problem, here's who has it, here's what
I built, here's what it costs, here's what broke and what I did about it, here's what I'd
build next and what I'd cut. Every claim backed by a document in the repo.

That's a hire-able conversation with or without prior job titles.
