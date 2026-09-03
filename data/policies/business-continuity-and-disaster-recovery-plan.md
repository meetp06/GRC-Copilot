# Business Continuity and Disaster Recovery Plan

**Owner:** Head of Engineering · **Last reviewed:** 2026-05-28 · **Review cycle:** annual

## Backups

Production databases are backed up continuously through point-in-time recovery with a
retention window of 35 days. Full snapshots are taken nightly and replicated to a second
AWS region. All backups are encrypted at rest with AES-256 using the same KMS
customer-managed keys as production. Backup restores are tested quarterly against a
non-production environment and the result is recorded.

## Recovery objectives

The recovery time objective (RTO) for the production service is 4 hours. The recovery point
objective (RPO) is 1 hour. These objectives apply to a full loss of the primary AWS region.
Individual component failures are expected to recover automatically within minutes and are
not covered by these objectives.

## Failover architecture

The production service runs across three availability zones in the primary region. Databases
run in a multi-AZ configuration with automatic failover. Static assets and backups are
replicated to a secondary region. Failover to the secondary region is a documented manual
procedure, not automatic.

## Disaster recovery testing

A full disaster recovery exercise is performed annually. The most recent exercise was
completed in January 2026 and met the 4 hour RTO. Findings from the exercise are tracked as
action items to closure.

## Crisis communication

During a declared continuity event the incident commander owns customer communication.
Status is published to the public status page within 30 minutes of declaration and updated
at least hourly until resolution.
