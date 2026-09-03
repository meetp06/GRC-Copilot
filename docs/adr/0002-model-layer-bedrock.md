# ADR-0002: Use AWS Bedrock as the model layer

**Status:** Accepted
**Date:** 2026-08-31

## Context

GRC Copilot needs an LLM. The buyers I'm modelling (companies selling into regulated
enterprises) care where their policy documents go. The target job description explicitly
names AWS Bedrock and secure cloud environments.

Constraints: I have ~$200 in AWS credits over 6 months and want to stay under $5/month
after that. I need cheap tokens for a fast dev loop, and a credible story about data
handling for a compliance product.

## Decision

Use **Amazon Bedrock** via the `converse` API (boto3), with a model ID set by
`BEDROCK_MODEL_ID` in `.env`. Default to the cheapest available model for the dev loop and
route only hard steps to a stronger model later.

I do not hardcode a model ID in code — `scripts/check_bedrock.py` lists what is actually
enabled in my account and region, because model availability differs per account.

## Alternatives considered

### Direct provider APIs (Anthropic / OpenAI)
- Attractive: simplest possible setup, new models land 1-4 weeks earlier, excellent SDKs,
  generally better docs.
- Rejected because: separate billing outside AWS, and it weakens the core story of this
  project. A compliance product's first question from a buyer is "where does my data go?"
  Bedrock keeps inference inside the same AWS account, region, VPC, and CloudTrail audit
  trail as the data — which is the whole point of week 6.
- **When it would be the better call:** if I needed the newest frontier model the day it
  ships, or if the project had no cloud-governance requirement.

### Self-hosted open weights (Llama / Mistral on my own GPU)
- Attractive: near-zero marginal token cost, full data control, real "air-gapped" story.
- Rejected because: I don't have a GPU, and renting one costs far more than API tokens at
  my volume. Managing inference infra would eat weeks I need for the agent and RAG work.
- **When it would be the better call:** genuinely air-gapped deployments, or high steady
  volume where the fixed GPU cost beats per-token pricing.

### Vertex AI / Azure OpenAI
- Attractive: equivalent managed offerings with their own gov-cloud tiers.
- Rejected because: the JD leads with AWS, I have AWS credits, and spreading across three
  clouds would mean learning three IAM models badly instead of one well.
- **When it would be the better call:** an employer already standardised on GCP or Azure.

## Consequences

**Good:** one bill, one IAM model, one audit trail. Bedrock Guardrails and PrivateLink are
available later without re-architecting. Directly matches the JD.

**Bad:** Bedrock has no free token allowance — every call costs money from day one, which is
why the `$1` budget alarm and `MAX_TOKENS_PER_RUN` cap exist. Model IDs and regional
availability are fiddly. Slightly behind direct providers on newest models.

## The interview answer

"Bedrock, so the model, the documents, and the audit logging all sit inside one AWS
compliance boundary — for a GRC product, 'where does my data go' is the first buyer
question, and a direct API call to a third party is a worse answer."
