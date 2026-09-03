# Cost Guardrails

Target: **under $5/month.** This project has to survive for months on a small budget while
you job hunt. A surprise bill kills it.

## The hard rules

1. **AWS Budgets alarm at $1**, set before writing any code. Email notification. Then a
   second at $10 as a backstop.
2. **Never create an OpenSearch Serverless (Classic) collection.** It bills for minimum
   capacity units whether or not you query it — roughly $350/month idle. Many AWS RAG
   tutorials use it without warning you. This is the single most expensive mistake available
   in this project.
3. **No NAT Gateway.** ~$32/month for nothing. Use VPC endpoints if you need private
   networking at all.
4. **No always-on compute.** Lambda, S3, DynamoDB on-demand. Nothing that bills while idle.
5. **Cheapest model in the dev loop.** Only route genuinely hard steps to a stronger model,
   and only after traces show which steps those are.
6. **`MAX_TOKENS_PER_RUN` stays enabled.** It's checked before each model call, so a runaway
   loop can't spend past the cap.

## Where money actually goes

| Item | Notes |
|------|-------|
| Bedrock tokens | The main cost. No free tier — you pay from call one. |
| Embeddings | One-time per document version, cheap. Re-embedding *everything* nightly is not — make the pipeline incremental. |
| S3 | Pennies at this scale. |
| Lambda | Free tier covers this workload comfortably. |
| DynamoDB on-demand | Effectively free at this volume. |
| CloudWatch Logs | **Set retention.** Infinite retention is a slow leak. 30 days is plenty. |

Verify current Bedrock per-model pricing yourself before choosing a model — it changes, and
per-token prices vary by an order of magnitude across models.

## Credits

New AWS accounts have historically come with promotional credits. Check what your account
actually has in Billing → Credits, and note the expiry. Don't assume — plan for the cost
without them.

## Habits that keep it cheap

- Cache eval runs. Re-running 50 questions to check one prompt change is wasteful — cache
  retrieval results and only re-run generation.
- Test tool logic offline with mocks. Most of your unit tests need no model call at all.
- Use the smallest `maxTokens` that works. You pay for output.
- Watch the Langfuse cost-per-questionnaire number from week 5. If it climbs, find out why
  before it compounds.
- Check the AWS Cost Explorer weekly. Make it a Friday habit.

## If you get an unexpected charge

1. Cost Explorer → group by service → find the source
2. Delete or disable it immediately; investigate after
3. **AWS support will often waive a first-time accidental charge** if you open a billing
   ticket and explain. Ask politely. It works more often than people expect.
4. Log it in `MISTAKES.md`. Cost incidents are legitimate engineering war stories.
