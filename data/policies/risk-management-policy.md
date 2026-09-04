# Risk Management Policy

**Owner:** Head of Security · **Last reviewed:** 2026-06-30 · **Review cycle:** annual

## Risk assessment

A formal risk assessment covering the production environment, the corporate environment, and
the vendor portfolio is performed annually and on any material change to the architecture.
Risks are scored on likelihood and impact on a 1 to 5 scale; the product of the two gives an
inherent risk rating.

## Risk register

All identified risks are recorded in a risk register with an owner, an inherent rating, the
mitigating controls, a residual rating, and a target date. The register is reviewed monthly
by the Head of Security and quarterly with the leadership team. Risks rated High or above
require a documented treatment plan.

## Risk acceptance and exceptions

A risk may be accepted rather than mitigated only with written approval from the Head of
Security, and from the CEO where the residual rating is High or above. Every accepted risk
carries an expiry date of no more than 12 months, after which it is reassessed rather than
renewed automatically.

## Control framework

Our control set is mapped to NIST SP 800-53 Rev. 5. The mapping is maintained as part of the
risk register so that each control has a named owner and a named source of evidence. We use
the framework for internal structure and gap analysis; it is a mapping, not an external
attestation.

## Control mapping summary

The mapping below is the summary view; the full matrix lives in the risk register.

- SC-28 Protection of Information at Rest — Information Security Policy, encryption at rest
- SC-8 Transmission Confidentiality and Integrity — Information Security Policy, encryption
  in transit
- AC-2 Account Management — Access Control Policy, access reviews and offboarding
- AC-6 Least Privilege — Access Control Policy, least privilege
- IA-2 Identification and Authentication — Access Control Policy, authentication
- AU-2 Event Logging — Vulnerability Management Policy, logging and monitoring
- RA-5 Vulnerability Monitoring and Scanning — Vulnerability Management Policy, scanning and
  remediation timelines
- IR-4 Incident Handling — Incident Response Plan, response process
- CP-9 System Backup — Business Continuity and Disaster Recovery Plan, backups

## Internal audit

An internal control review is performed twice a year against the mapped control set. Gaps
are entered in the risk register with an owner and a target date. Review evidence is
retained for 3 years.
