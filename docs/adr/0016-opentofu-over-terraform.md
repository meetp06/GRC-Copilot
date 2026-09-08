# ADR-0016: OpenTofu rather than Terraform

**Status:** Accepted
**Date:** 2026-09-07

## Context

Week 6 needed infrastructure as code. The obvious tool is Terraform — except that in August
2023 HashiCorp relicensed it from MPL 2.0 to the Business Source Licence, and it was removed
from homebrew-core as a result. `brew install terraform` now fails with "No available formula".

BUSL is not open source. It forbids use that "competes" with HashiCorp's own products, a
restriction whose boundary is decided by HashiCorp rather than by a court, and it converts to
MPL only four years after each release.

## Decision

OpenTofu 1.12.6. Same HCL, same provider registry, `tofu` instead of `terraform`.

## Alternatives considered

### Terraform via the HashiCorp tap

- **Why it's attractive:** it is what job descriptions name, what documentation assumes, and
  what most teams run.
- **Why I did not pick it here:** the licence is a real constraint on a public portfolio
  repository. And the files are identical — anything here runs under `terraform` unchanged, so
  the interview answer is not "I do not know Terraform", it is a licence decision I can
  explain.
- **When it would be the better call:** an employer who already runs Terraform Cloud, or a
  team wanting HashiCorp's commercial support.

### AWS CDK

- **Why it's attractive:** infrastructure in Python, which is the rest of this project.
- **Why I did not pick it here:** it generates CloudFormation, so a failed deploy is debugged
  through a stack-events console rather than a plan diff. And "I have used Terraform" is on
  more job descriptions than CDK by a wide margin.
- **When it would be the better call:** an AWS-only shop already invested in CloudFormation.

### The AWS console

- **Why it's attractive:** no tooling, immediate.
- **Why I did not pick it here:** nothing is reviewable, nothing is repeatable, and — for a
  project that must not cost money — nothing enumerates what exists so it can all be deleted.
  `tofu destroy` is the feature that makes deploying safe.

## Consequences

**Good:** MPL 2.0, so no licence question on a public repository. `tofu fmt`, `plan`, `apply`
and `destroy` behave as Terraform does, and the `.tf` files carry no OpenTofu-specific syntax
— someone can run them with Terraform and never notice.

**Bad:** every tutorial says `terraform`, and the muscle memory is wrong. Some newer providers
publish to the Terraform registry first. And a CI action is `opentofu/setup-opentofu` rather
than the far more widely used `hashicorp/setup-terraform`.

**Neutral, and worth stating:** state is local. An S3 backend needs a bucket and a lock table
that exist before the first apply, which is a bootstrap problem worth solving when more than
one person runs this. `terraform.tfstate` is gitignored — it holds resource ids and can hold
secret values in plaintext.

## The interview answer

"OpenTofu, because Terraform went to the Business Source Licence in 2023 and this is a public
repository. The files are identical HCL — you could run them with Terraform and not notice —
so it is a licence decision rather than a technical one, and I would happily use either."
