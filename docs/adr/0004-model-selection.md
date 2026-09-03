# ADR-0004: Bedrock model selection for week 1

**Status:** Accepted
**Date:** 2026-09-03

## Context

The week 1 agent loop needs a Bedrock model that supports: tool calls, parseable JSON, and a per-token cost low enough to keep total project spend under $5/month.

## Decision

Use `amazon.nova-lite-v1:0` with on-demand pricing in `us-east-1`. It supports tool use via the Converse API, has a 300K-token context window, and costs $0.06/M input and $0.24/M output tokens. Week 1 spend was ~$0.006 total.

## Alternatives considered

### `amazon.nova-micro-v1:0`
- Attractive: cheapest Nova text model (<!-- TODO: exact $/M from the AWS Bedrock pricing page -->), and 128K context, which is far more than this loop needs
- Rejected because: it cannot reliably drive a tool-calling loop. At `maxTokens=1024` it ran past the cap and truncated mid-answer. Raising it to 2048 did not fix it — 3 of 5 questions then failed with `ModelErrorException: Model produced invalid sequence as part of ToolUse`. Context was never the limit; tool-use reliability was.
- **When it would be the better call:** non-agent prompt-rewriting, or a task with truly tiny input/output

### `anthropic.claude-3-haiku-20240307-v1:0`
- Attractive: stronger reasoning than lite, available on-demand in us-east-1
- Rejected because: untested at this point; better reserved for week 3 when verifier reasoning quality matters more
- **When it would be the better call:** once the rest of the system is stable and reasoning quality becomes the bottleneck

### Provisioned throughput (any model)
- Attractive: consistent latency
- Rejected because: bills for minimum capacity whether in use or not; kills the under-$5/month budget
- **When it would be the better call:** a production service with predictable traffic

## Consequences

**Good:** completes every question in the week 1 set, no idle cost, context window far larger than the loop needs

**Bad:** nova-lite wraps JSON in `<thinking>` tags (had to add a post-processor); per-token cost ~2× micro, but acceptable

## The interview answer

"I picked nova-lite because micro was cheaper per token but more expensive per answer — it truncated at my token cap, and raising the cap just moved the failure to invalid tool-use sequences that Bedrock rejected outright. Cheapest model that actually finishes a run wins."
