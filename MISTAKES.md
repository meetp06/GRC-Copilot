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

### Sep/2/2026 — Week 1 mistakes

1. **Region/output swapped**
Symptom: sts.Global.amazonaws.com DNS failure · Cause: typed Global at the region prompt; boto3 substitutes region into the hostname with no validation · Fix: aws configure set region us-east-1 · Lesson: bad config surfaces as a network error.

2. **Root access keys**
Symptom: ARN ended :root, UserId == Account · Cause: made keys from the root account instead of an IAM user · Fix: deleted them, created grc-copilot user with 2 scoped actions · Lesson: IAM policies don't apply to root — there's no least-privilege version of that key.

3. **git-secrets passed a real-looking key ← strongest**
Symptom: committed a fake AKIA… key, hook printed Passed · Cause: git-secrets reads patterns from git config; none were registered, so it matched nothing · Fix: registered AWS patterns + added detect-aws-credentials · Lesson: fail-open security fails silently. Found only by attacking my own setup.

4. **Stale checklist**
Symptom: bedrock:Converse in my plan; Model access page gone · Cause: AWS moved, docs didn't · Fix: dropped the fake action · Lesson: get permission names from the API's error messages, not from docs.

5. **IAM blamed the action, not the resource**
Symptom: "no policy allows bedrock:InvokeModel" — but it does · Cause: call was us-west-2, policy scoped us-east-1 · Fix: none needed, working as intended · Lesson: read the resource ARN before editing the action list.

6. **Wrong step count**
Symptom: run stopped at step 2, reported 8 · Cause: failure return used max_steps not step · Fix: one word · Lesson: a wrong number is worse than no number — it sends you hunting the wrong bug.

7. **Correct answer, unparseable**
Symptom: Could not parse JSON on a right answer · Cause: nova-lite prefixes <thinking>; parser assumed JSON first · Fix: take outermost {...} · Lesson: never assume model output starts where you expect.

8. **Cheapest model wasn't cheapest**
Symptom: nova-micro truncated at maxTokens=1024 · Cause: rambled past the cap · Fix: back to nova-lite · Lesson: a wasted run costs more than the token savings.

### Sep/4/2026 — Week 2 mistakes

9. **IAM named the action, the resource was the problem — again ← strongest**
Symptom: `AccessDeniedException` on `bedrock:InvokeModel` for Titan embeddings, an action the policy already grants and uses daily · Cause: the policy scopes `InvokeModel` to a resource list containing only `amazon.nova-*`; Titan was never in it · Fix: added `arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0` to the list · Lesson: this is entry 5 a second time. The error message leads with the action because that is what I asked for; the resource ARN at the end is what actually failed. I now read AWS denials backwards — resource first, then action.

10. **Least privilege worked, and that looked like a bug**
Symptom: new model blocked; first instinct was that something was misconfigured · Cause: nothing. The week 1 policy correctly refused a model I had never authorised · Fix: none needed beyond granting the one ARN · Lesson: a deny from my own guardrail is the guardrail reporting for duty. The tell is whether I can name the exact permission I never granted — if I can, it is working; if I cannot, it is broken.

11. **The venv broke because I moved the folder**
Symptom: `pre-commit` and `pytest` failed with `bad interpreter: /Users/meet/Downloads/learna2z/grc-copilot/.venv/bin/python3.14` — a path that no longer exists · Cause: venv console scripts hard-code an absolute interpreter path in their shebang line; I moved the project from `learna2z/grc-copilot` to `grc-copilot` · Fix: rewrote the stale path in every file under `.venv/bin` and in `pyvenv.cfg` · Lesson: `.venv/bin/python` kept working the whole time because it is a symlink, not a script, so the breakage stayed hidden until a git hook needed a console script. A partially working environment hides longer than a completely broken one.

12. **Two ruff versions fighting each other**
Symptom: every commit reformatted files that the previous commit had just formatted, in a loop · Cause: my venv has ruff 0.16.5, `.pre-commit-config.yaml` pins `v0.6.9`, and they disagree about line breaking · Fix: pinned the venv to the same version the hook uses, so local formatting and the gate are the same tool · Lesson: a linter pinned in two places with two values is not pinned. The hook version is the one that decides, so that is the one the editor and the venv have to match.

13. **`pytest` and `python -m pytest` disagreed**
Symptom: `python -m pytest` passed; bare `pytest` failed every test file with `ModuleNotFoundError: No module named 'src'` · Cause: the module form puts the working directory on `sys.path`, the console script does not · Fix: added `pytest.ini` with `pythonpath = .` · Lesson: if a test suite only passes when invoked one particular way, the suite depends on the invocation. CI will use the other one.

14. **A prompt rule that made things worse**
Symptom: the model wrote "No, engineers do not get unrestricted rights over live systems" and then set `answerable: false` — a correct answer flagged as a refusal, on q_015, q_020 and q_033 · Cause: it read `answerable` as "is the answer yes" rather than "do the extracts support an answer" · Fix: attempted — added a rule to the system prompt spelling out the difference. It made things worse: answerable accuracy went 91% → 87%, and on q_025 the model quoted my instruction text back as its answer. Reverted to the three-sentence prompt and accepted the bug · Lesson: on a small model, instructions compete with the task for attention. A rule that fixes one case can cost more than the case was worth, and the only way to know is to re-run the eval set. I would not have caught this by reading outputs.

15. **The refusal cascade paid for itself on day one**
Symptom: three answers where the structured `answerable` flag said "refused" and the answer text plainly was not a refusal · Cause: the model conflating a negative answer with an inability to answer (entry 14) · Fix: none to the cascade — it did its job. The disagreement count is what surfaced the bug · Lesson: I designed the cascade to save money by only calling a judge on disagreements. Its real value turned out to be that the disagreements themselves are a bug detector. Two cheap signals that should agree are worth more than one expensive signal.

16. **A results file overwrote itself**
Symptom: wanted to compare two runs of the strict prompt; the first result was gone · Cause: I named results `YYYY-MM-DD-<config>.json`, and tuning a prompt means running the same config repeatedly on the same day · Fix: timestamped to the minute · Lesson: I wrote the filename thinking about how I would read the history later, not about how often I would write to it. The write pattern decides the key, not the read pattern.

17. **My eval set could not see the thing I was testing**
Symptom: hybrid BM25 + vector retrieval scored worse than vector alone at every fusion weight, so I nearly rejected it · Cause: not one of my 35 questions asked for a literal token like `SC-28` or `AES-256` — the exact case BM25 exists to handle. The eval measured only BM25's damage, never its benefit · Fix: added a five-question `exact` band, re-ran, and BM25 did win that band 90% → 100%. Rejected hybrid anyway, on the full picture · Lesson: a technique that loses on a set with no test for its strength has not been evaluated, it has been excluded. Before rejecting anything, I now ask what question would have to be in the set for this to win — and check whether one is.

### Sep/4/2026 — Week 3 mistakes

18. **I compared configs with single runs and never measured the noise ← strongest**
Symptom: the same pipeline, same config, same `temperature=0.0`, scored 84% on one run and 87% on another · Cause: I assumed temperature 0 meant deterministic and never checked. Two identical runs inside one process agreed on all 45 questions, so the drift is across processes, not within one · Fix: ran every A/B three times — config A twice for a noise floor, config B once — and treated any difference smaller than the A-to-A gap as nothing. Amended ADR-0008, where the 91% vs 87% prompt comparison sits inside the error bars · Lesson: a comparison without a repeat of the same config is not a measurement, it is one sample. The first thing to run is the thing you are not changing.

19. **My verifier passed every test I built it to fail**
Symptom: the new verifier approved a draft claiming we hold a SOC 2 Type II report, sourced from a passage about what we require of our *vendors*, and approved an invented "keys rotate every 90 days" against a source saying annual · Cause: I asked it for one boolean, `supported: true/false`. Agreeing is free · Fix: changed the schema, not the prompt — every claim now needs the verbatim sentence that supports it plus whether that sentence is about us, and `quote_is_real()` checks in Python that the quote occurs in the source. 2/4 to 4/4, same model, same temperature · Lesson: this is ADR-0008's finding a second time. When a model behaves wrong, ask what the schema *requires* before rewriting the prompt. A boolean is an opinion; a quote is checkable.

20. **I told the model how to give up, and it did**
Symptom: after the verifier rejected a draft, 3 answerable questions came back as refusals · Cause: my retry prompt ended "if the extracts genuinely do not support an answer, set answerable to false rather than trying again" — an escape hatch, taken by a model that had just been criticised · Fix: none. Removing the sentence moved 2 questions, in opposite directions, which entry 18 says is noise · Lesson: I nearly "fixed" this from a single run before measuring variance. Worth remembering that the fix I was confident about was indistinguishable from doing nothing.
