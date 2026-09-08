# Compliance posture of GRC Copilot itself

**Last reviewed:** 2026-09-07 · **Scope:** the `dev` deployment described in `infra/`

A product that automates compliance answers invites an obvious question: **is the product
itself compliant?**

The honest answer is no, and this document says so specifically rather than generally. What
follows is a control-by-control statement of what is implemented, what is partial, and what is
absent, using the same NIST SP 800-53 Rev 5 catalogue the product maps customer policy against.

## Scope statement, read this first

This is **not** an attestation. It is a self-assessment of a portfolio project, written by the
person who built it, with no independent review.

Specifically:

- **No audit.** No SOC 2, no ISO 27001, no penetration test, no third-party review of any kind.
- **One environment, one user.** A `dev` deployment in one AWS account, operated by one person.
  Several controls below are marked "not applicable" only because there is no second person for
  them to apply to, and they would become applicable on the day there is.
- **No production data.** The corpus is three public university policies. No customer has ever
  used this and no real security documentation has been through it.
- **The evidence is code, not records.** A control marked implemented points at a Terraform
  resource or a test. None of it points at an operating record, which is what an auditor would
  ask for — "the policy says quarterly access reviews" and "here are four years of review
  records" are different claims, and this document can only make the first kind.

If any of that changes, this document is wrong until it is rewritten.

## What is implemented

Each row names where the evidence is, so it can be checked rather than believed.

| Control | Status | Evidence |
|---|---|---|
| **SC-28** Protection of information at rest | Implemented | Customer-managed KMS keys with rotation on S3 (`infra/storage.tf`), both DynamoDB tables, Secrets Manager, and CloudWatch Logs. A bucket policy denies any upload that is not `aws:kms` encrypted. |
| **SC-8** Transmission confidentiality | Implemented | API Gateway is HTTPS-only. The bucket policy denies any request with `aws:SecureTransport=false`. |
| **SC-13** Cryptographic protection | Implemented | AWS-managed AES-256 under customer-managed keys. No cryptography is implemented in this codebase. |
| **AC-6** Least privilege | Implemented | One IAM role for the Lambda, every action named individually (`infra/iam.tf`). No `s3:PutObject` — the request path reads the index and never writes it, so a compromised API cannot alter the corpus its answers come from. |
| **AC-3** Access enforcement | Partial | Every route except `/` and `/health` requires a shared `X-API-Key`, compared with `hmac.compare_digest`. See the gaps below — a shared key is not access control. |
| **AU-2** Event logging | Implemented | API Gateway access logs and Lambda logs to CloudWatch, both encrypted, both with retention set. Access logs deliberately exclude request and response bodies. |
| **AU-11** Audit record retention | Implemented | 14 days, set explicitly. Infinite retention is a cost leak, and these logs may contain fragments of customer questionnaires. |
| **SI-12** Information handling and retention | Implemented | DynamoDB TTL expires checkpoints after 30 days. S3 lifecycle expires non-current versions after 30 days and aborts incomplete uploads after 7. |
| **CP-9** System backup | Implemented | Point-in-time recovery on both DynamoDB tables; versioning on the bucket. |
| **CM-2** Baseline configuration | Implemented | All 27 resources in OpenTofu. Nothing was created by hand. |
| **CM-3** Configuration change control | Partial | Changes go through Git with CI running lint, tests, `tofu validate` and tfsec. There is no second reviewer, because there is one person. |
| **RA-5** Vulnerability monitoring | Implemented | `pip-audit` for dependency CVEs, `bandit` for Python issues, `tfsec` for Terraform, `gitleaks` for committed secrets — all on every pull request. |
| **SA-11** Developer testing | Implemented | 124 tests, all offline. The eval gate fails the build if retrieval regresses below measured floors. |
| **SA-15** Development process | Implemented | 17 ADRs recording decisions and their alternatives; 42 entries in `MISTAKES.md` recording failures and their causes. |
| **IA-5** Authenticator management | Partial | The API key lives in Secrets Manager under a customer-managed key, never in an environment variable or in Terraform state. Rotation has been exercised once (2026-09-07) and is manual, unscheduled, and not a true revocation: `_expected_api_key()` is cached per Lambda container, so a warm container honours a withdrawn key until it is recycled. |
| **SI-10** Information input validation | Implemented | Uploads are size-capped, row-capped, UTF-8 validated, and checked for duplicate ids. Exported CSV cells are neutralised against spreadsheet formula injection. |

## What is not implemented, and what it would take

These are absent, not partial. Several are single points of failure for a real deployment.

| Control | Absent because | What it would take |
|---|---|---|
| **AC-2** Account management | There are no accounts. One shared key, no identity, no per-tenant authorisation — anyone holding the key can read and approve every tenant's answers. | Real authentication (Cognito, or an OIDC provider) and a tenant id on every row. This is the deployment blocker. |
| **AU-6** Audit review and analysis | Logs are written and nobody reads them. Alarms fire on error rate and spend; nothing reviews access patterns. | Someone whose job it is, or a query that runs on a schedule. |
| **AU-9** Protection of audit information | The account operating the service can also delete its own logs. | A separate logging account, which is the standard answer and is not proportionate here. |
| **IR-4** Incident handling | No incident response plan exists for this service. The product answers questions *about* incident response and has none of its own. | A written plan, and someone on call. |
| **CP-2** Contingency planning | Backups exist; no restore has ever been tested. An untested backup is a hypothesis. | Restore into a scratch table and verify. |
| **AC-4** Information flow enforcement | The Lambda has unrestricted egress. It reaches Bedrock over the public internet. | A VPC with endpoints — which costs money and is why it is not here. |
| **SC-7** Boundary protection | No WAF, no VPC. API Gateway throttling (20 burst, 10/sec) is the only limit. | AWS WAF, at roughly $6/month. |
| **PS-\*** Personnel security | One person, no organisation. Not applicable today; applicable the day there are two. | — |
| **CA-2** Control assessments | This document is a self-assessment. Nothing independent has reviewed it. | An assessor. |

## The gaps that matter most

Three, in the order I would fix them:

**1. There is no authentication worth the name.** A shared API key gives no identity, no
per-tenant authorisation, and no revocation short of rotating it for everyone. A reviewer
approving an answer is not identified — the `confirmed_by` column on a control mapping holds a
name that anyone with the key can supply. In a product whose output is an attestation, "who
approved this" is not a nice-to-have.

**2. The checkpoint and job data is encrypted at rest and readable by the service.** That is
correct for the service. It also means the questionnaire text and retrieved policy extracts of
every tenant sit in tables that one IAM role can read entirely. There is no per-tenant
encryption context and no row-level scoping.

**3. Backups have never been restored.** Point-in-time recovery is enabled on both tables. It
has never been exercised, so what exists is a configuration setting, not a demonstrated
capability. This is exactly the gap the product's own eval-set discipline exists to prevent
elsewhere in this repo, and it is unmeasured here.

## Why this document exists in this repo

Two reasons, and the second is the real one.

The stated reason is that a compliance product should be able to describe its own posture.

The honest reason is that writing it surfaced things the code did not. Enumerating AC-2
against this service is what made it obvious that "the reviewer's name" is a free-text column
with nothing behind it. That is the same exercise the product performs for a customer —
mapping controls to evidence and finding out where there is none — pointed at itself.

The gap report this produces is worse than the one the product generates for its test corpus.
That seems worth saying out loud.

## Related

- [docs/THREAT-MODEL.md](THREAT-MODEL.md) — the attacker's view of the same system
- [docs/adr/0017-serverless-and-what-it-costs.md](adr/0017-serverless-and-what-it-costs.md) — why the architecture is shaped this way
- [MISTAKES.md](../MISTAKES.md) — 42 entries, including the cross-tenant defect that reached the deployed API
