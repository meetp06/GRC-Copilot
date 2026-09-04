# Asset and Endpoint Management Policy

**Owner:** Head of IT · **Last reviewed:** 2026-06-05 · **Review cycle:** annual

## Asset inventory

An inventory of all company-owned endpoints and production cloud resources is maintained
automatically. Endpoints are enrolled in mobile device management at issue; an endpoint that
has not checked in for 30 days is investigated. Cloud resources are inventoried from the AWS
account and must carry an owner tag.

## Endpoint hardening

Company laptops enforce full-disk encryption, an automatic screen lock after 5 minutes,
endpoint detection and response software, and a host firewall. Local administrator rights
are removed by default and granted on request with justification. Configuration is enforced
through mobile device management and drift is reported weekly.

## Endpoint patching

Operating system and browser updates are enforced within 14 days of release for all
severities, and within 7 days for updates addressing a critical vulnerability. An endpoint
that is out of compliance for more than 21 days is blocked from accessing production
systems by conditional access.

## Removable media

Use of removable media for customer data is prohibited. USB mass storage is blocked by
policy on company laptops. Exceptions require approval from the Head of Security and are
reviewed quarterly.

## Media disposal

Decommissioned laptops are cryptographically erased before disposal. Cloud storage volumes
are deleted through the provider, relying on the provider's media sanitization controls. A
disposal record is retained for 3 years.
