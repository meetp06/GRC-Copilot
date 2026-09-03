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
