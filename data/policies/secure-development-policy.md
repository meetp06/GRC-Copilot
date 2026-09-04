# Secure Development Policy

**Owner:** Head of Engineering · **Last reviewed:** 2026-06-18 · **Review cycle:** annual

## Code review

Every change to production code requires review and approval by at least one engineer other
than the author before merge. Branch protection enforces this in the repository; it cannot
be bypassed by the author. Reviews cover correctness, security impact, and test coverage.

## Secrets management

Secrets are stored in AWS Secrets Manager and injected at runtime through environment
variables. Secrets are never committed to source control. Automated secret scanning runs on
every push and blocks the commit on a match. Discovered secrets are rotated within 24 hours.

## Dependency management

Third-party dependencies are pinned to explicit versions. Automated dependency alerts open a
pull request for each advisory. Dependencies with a known critical vulnerability follow the
7 day remediation timeline defined in the Vulnerability Management Policy.

## Change management

Changes are deployed through an automated CI/CD pipeline. The pipeline runs unit tests,
static analysis, and container image scanning, and blocks the deploy on a high-severity
finding. Every deploy is traceable to a merged pull request and its approver. Emergency
changes may bypass the normal review window but require retrospective approval within one
business day.

## Environment separation

Development, staging, and production run in separate AWS accounts with no shared
credentials. Production customer data is never copied into development or staging. Test data
is synthetic.
