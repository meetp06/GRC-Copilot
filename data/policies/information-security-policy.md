# Information Security Policy

**Owner:** Head of Security · **Last reviewed:** 2026-06-01 · **Review cycle:** annual

## Encryption at rest

All customer data stored in production is encrypted at rest using AES-256. Encryption keys
are managed in AWS KMS using customer-managed keys (CMKs) with automatic annual rotation
enabled. This covers Amazon S3 buckets, Amazon RDS databases, and Amazon EBS volumes.
Database snapshots and backups inherit the same encryption. No customer data is written to
unencrypted storage at any point in the pipeline.

## Encryption in transit

All data transmitted between clients and our services uses TLS 1.2 or higher. TLS 1.0 and
1.1 are disabled at the load balancer. Internal service-to-service traffic within our VPC
also uses TLS. Certificates are issued and rotated automatically through AWS Certificate
Manager.

## Data retention and deletion

Customer data is retained for the duration of the subscription plus 30 days. On written
deletion request, production data is deleted within 30 days and backup copies expire within
a further 35 days. Deletion is confirmed in writing to the customer.

## Data classification

Data is classified as Public, Internal, Confidential, or Restricted. Customer data is
classified Restricted by default. Restricted data may not be copied to local workstations
or to non-production environments.
