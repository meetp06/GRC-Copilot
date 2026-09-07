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

21. **A dedup set that only recorded the rows it kept**
Symptom: rejected a question in the review CLI, `list` still showed it as pending · Cause: `_pending()` walked checkpoints newest-first and used one dict for both deduplication and results, adding a thread only when its checkpoint matched `needs_review`. The newest checkpoint said `rejected`, so the thread was never marked seen, and the older `needs_review` checkpoint right behind it was picked up instead · Fix: a separate `visited` set, marked for every thread regardless of whether it matched · Lesson: "first match per key" and "first row per key" are different loops. If the dedup structure is only written on the branch that keeps a row, it is not deduplicating anything — it is just remembering the matches.

22. **The answers are written from the wrong side of the table**
Symptom: an exported answer reads "Yes, your backups are encrypted to the same standard as your production data" — we are the vendor answering, so it should be "our" · Cause: the drafter is shown the buyer's question verbatim and never told whose voice to answer in. It mirrors the questioner's pronouns · Fix: not yet applied. It is cosmetic in the eval set, where nothing scores wording, and embarrassing in the export, which is what a customer actually receives · Lesson: my metrics measure whether an answer is correct and cited. Nobody was measuring whether it was *sendable*. The eval set inherited that blind spot from the day it was written.

23. **CSV injection in the one file a customer actually opens ← strongest**
Symptom: none — found by a security review of my own commit, not by anything failing · Cause: `export()` wrote answer and question text straight into a CSV. Excel and Google Sheets evaluate any cell beginning with `=`, `+`, `-`, `@`, tab or carriage return, so a cell reading `=cmd|'/c calc'!A1` can execute on the machine that opens the file · Fix: prefix those cells with an apostrophe, which spreadsheets read as "this is text". Six parametrised tests plus an end-to-end one that plants a formula in the questionnaire and asserts it comes back inert · Lesson: CLAUDE.md told me to treat questionnaire input as hostile and I applied that to the *model* — prompt injection — and not at all to the export. The uploaded question round-trips through the whole system into a spreadsheet on the buyer\'s laptop, and that path never went near a model. I was guarding the interesting attack surface and ignoring the boring one.

24. **I planned for throttling that never came**
Symptom: none — the failure I was told to expect did not happen. WEEK3.md says "concurrency will bite you, start at 3-5, you will hit Bedrock throttling", so I shipped a default of 4 · Cause: I took a plan\'s prediction as a measurement. Nova Lite on-demand in us-east-1 ran 50 questions at concurrency 50 with zero retries and zero errors · Fix: measured 4 / 20 / 50 (17.2s, 15.7s, 10.7s), set the default to 20 at the knee of the curve, and wrote the numbers into the code next to the constant · Lesson: a conservative default costs real wall-clock on every run forever, and I had picked mine to avoid a failure I never verified existed. Guessing low is still guessing.

25. **The model\'s confidence was worse than a score built from four cheap signals**
Symptom: calibrating against the golden set, the model\'s own stated confidence was 92% precise on the 36 it called "high" — three answers marked confident and wrong · Cause: the model\'s confidence is produced by the same pass that produced the answer, so it cannot be independent evidence about that answer. A model that misread a passage is confident *because* it misread it · Fix: a computed score from verifier-passed-first-time, retrieval margin, whether anything was cited, and the model\'s opinion as the weakest tiebreak. 31 marked high, 31 correct, 100% · Lesson: "the model says 90%" is not a confidence score, it is the model\'s mood. The signals worth using are the ones produced by something other than the thing being scored.

### Sep/7/2026 — Week 4 mistakes

26. **My heading detector was wrong, and it nearly sent me down a much harder road ← strongest**
Symptom: the inventory reported "no detectable headings" for 4 of 5 real PDFs, including one whose headings are plainly `I. Purpose`, `II. Scope`, `III. Definitions` · Cause: my heading regex required digits (`4.2 Access Control`) and did not match Roman numerals or single letters · Fix: two more patterns; that document went from 0 headings to 17 · Lesson: the wrong answer pointed at rebuilding structure from font data, which is far more work and far more fragile. I was one regex away from building the wrong thing. When a measurement says every input is broken, suspect the measurement.

27. **A count is not a quality check, for the third time**
Symptom: the font-based heading path produced 33 sections for one document and passed my gate, which was `sections >= 3` · Cause: 18 of those sections had zero body text — a cover page, a table of contents, a revision table and a signature block, every line of which is styled like a heading · Fix: drop sections with no prose and reject table-of-contents lines; 33 became 13 real ones · Lesson: this is week 2's hit-rate-vs-recall and week 3's `_pending` bug in a third costume. I keep writing gates that count rows instead of looking at them.

28. **I called a document garbage after reading twelve lines of it**
Symptom: I looked at the first 12 headings of the ASU policy, saw `Version 1.0`, `Contents`, `Document`, and told Meet the font method had produced junk · Cause: I read the front matter and stopped. Sections 17 onwards were `Overview`, `Purpose`, `Scope`, `Roles and Responsibilities`, `Policy`, `Definitions` — a correctly parsed policy · Fix: printed every section with its body length before judging, then dropped the empty ones · Lesson: I made a confident claim from a truncated view and had to retract it in the next message. Print the whole thing before drawing the conclusion.

29. **Three of five documents were not usable, and one was not a policy**
Symptom: of 5 public university PDFs, 2 parsed cleanly, 1 parsed with table corruption, 1 had no recoverable structure, and 1 was a 70-page PowerPoint about incident response · Cause: normal. This is what a folder of real documents looks like · Fix: a parse cascade that records which method won and refuses documents it cannot segment, plus a genre check that rejects slide decks before they reach the index · Lesson: the slide deck is the one that matters. Nothing else in the pipeline would have noticed, and it would have been indexed and cited to a customer as our own policy. Detecting that a document is not what it claims to be is part of ingestion, not a preprocessing detail.

30. **I documented a benefit the tool does not provide**
Symptom: I wrote in a docstring that Dagster "will not re-embed unless the documents actually changed", then re-ran the asset with nothing changed and watched it re-embed the whole corpus in 11.5s and pay $0.000148 again · Cause: I assumed an asset graph implies caching. Dagster tracks staleness and shows it in the lineage view, but `asset materialize --select` runs what you select; skipping needs an AutomationCondition this pipeline does not have · Fix: corrected the docstring and the module header to say what the tool actually does here · Lesson: I wrote the justification for the dependency before testing the justification. The check took one command and would have caught it before it was committed as documentation.

31. **Eyeballing showed me the good mappings and hid the rest ← strongest**
Symptom: none visible. The control mapper looked fine — `AU-02 Event Logging <- C. Audit and Accountability` at 0.523, `IR-08 <- E. Incident Response` at 0.720 — and I shipped a 0.40 threshold on that basis · Cause: I inspected the top proposals, which are by construction the best ones. ADR-0013 recorded the missing labelled set as a known gap and I moved on anyway · Fix: labelled 19 sections blind to the mapper\'s output, including 4 that satisfy no control, then swept the threshold. At 0.40 precision was **24%** — three of every four mappings wrong. Moved to 0.50: precision 78%, false positives 37 to 2, recall 38% to 22% · Lesson: sorting by confidence and reading the top of the list is a demo, not a measurement. And a known gap I write down and skip is still a gap — MISTAKES entry 17 said this in week 2 and I did it again in week 4.

32. **I picked 0.50 over the best F1, on purpose**
Symptom: not a bug. 0.45 scores F1 0.36 against 0.50\'s 0.34, so the metric says 0.45 · Cause: F1 weights a false positive and a false negative equally, and this product does not. A missed mapping surfaces in the gap report as a control with no policy, which is conservative and gets written · Fix: chose 0.50 and wrote the reason next to the constant, so the next person does not "fix" it back to the better F1 · Lesson: the metric encodes an assumption about which error costs more. When that assumption is wrong for the product, the number to optimise is not the one the textbook names.

33. **Raising the threshold changed nothing, because nothing deleted the old edges**
Symptom: raised MIN_CONFIDENCE from 0.40 to 0.50, re-ran propose, saw "proposed 14 edges" — and the gap report still said 274 of 324, exactly as before · Cause: `propose()` used `INSERT OR REPLACE`, which replaces a row with the same primary key and leaves every superseded edge in place. 80 stale proposals from the old run were still counting as coverage · Fix: delete unconfirmed machine proposals before inserting, never touching human-confirmed ones. Honest numbers: 311 of 324 controls with no policy, 24 of 37 SOC 2 criteria · Lesson: INSERT OR REPLACE is an upsert, not a sync. Re-running a derivation step has to remove what the previous run derived, or the table accumulates every answer the system has ever given.

34. **I published inflated numbers and had to correct them**
Symptom: README and ADR-0013 said 274 of 324 controls lacked policy and 15 of 37 SOC 2 criteria had nothing. Both were flattering, and both were wrong · Cause: they counted the low-precision edges from entry 31 as real coverage · Fix: amended both rather than rewriting them, so the wrong figure and the reason it was wrong stay visible next to the corrected one · Lesson: a number in a README is a claim. This is the second amendment this project has needed after measuring something properly (ADR-0008 was the first), and both times amending beat quietly editing.
