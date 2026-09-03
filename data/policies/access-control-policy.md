# Access Control Policy

**Owner:** Head of Security · **Last reviewed:** 2026-05-14 · **Review cycle:** annual

## Authentication

All employee access to production systems requires single sign-on through our identity
provider with multi-factor authentication enforced. MFA cannot be disabled by end users.
Shared accounts are prohibited. Service accounts use short-lived credentials issued through
AWS IAM roles rather than long-lived access keys.

## Least privilege

Access to production is granted on a least-privilege basis. Engineers receive read-only
access by default. Write access to production databases requires a documented request,
manager approval, and is time-bound to a maximum of 8 hours through a just-in-time access
workflow.

## Access reviews

User access to production systems is reviewed quarterly by the system owner. The review
covers active accounts, permission levels, and the business justification for each. Findings
are remediated within 14 days. Access review evidence is retained for 3 years.

## Offboarding

Access is revoked within 4 hours of an employee's departure. Offboarding is triggered
automatically from the HR system. Hardware is collected and wiped within 5 business days.
