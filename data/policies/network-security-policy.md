# Network Security Policy

**Owner:** Head of Engineering · **Last reviewed:** 2026-06-27 · **Review cycle:** annual

## Network segmentation

Production runs in a dedicated AWS VPC with no shared network path to the corporate network.
Application and database tiers sit in separate private subnets. Databases have no route to
the internet. Only the load balancer tier is exposed publicly.

## Perimeter controls

Public endpoints sit behind a web application firewall with managed rule sets for the OWASP
Top 10, and behind AWS Shield for volumetric denial-of-service protection. Rate limiting is
applied per API key. Blocked request patterns are reviewed monthly.

## Remote access

There is no VPN into production. Engineers reach production through the just-in-time access
workflow described in the Access Control Policy, which issues short-lived AWS IAM role
credentials after manager approval. All sessions are logged to CloudTrail.

## Intrusion detection

Network flow logs and AWS GuardDuty findings are streamed to the logging account. High
severity findings page the on-call engineer and are triaged as a Sev2 incident or higher
under the Incident Response Plan. Flow logs are retained for 90 days.

## Firewall rule review

Security group and network ACL rules are defined in Terraform and changed only through the
reviewed pull request process. The full rule set is reviewed quarterly for rules that are
unused or broader than required. Any rule permitting 0.0.0.0/0 inbound to a non-load-balancer
resource is treated as a finding.
