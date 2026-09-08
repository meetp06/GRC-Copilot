# Storage: one KMS key, one bucket, two DynamoDB tables.
#
#   S3        the policy corpus and the vector index
#   DynamoDB  job records and LangGraph checkpoints
#   KMS       one customer-managed key over both
#
# Idle cost is the KMS key at $1/month. S3 at this size is fractions of a cent,
# and DynamoDB on-demand bills per request rather than per hour -- which is the
# whole reason it is here rather than RDS. See docs/COST-GUARDRAILS.md.

locals {
  name = "${var.project}-${var.environment}"
}

data "aws_caller_identity" "current" {}

# --------------------------------------------------------------------------
# encryption

resource "aws_kms_key" "main" {
  description = "GRC Copilot: customer policy documents and questionnaire answers"

  # Rotation is free and removes a finding from every compliance checklist this
  # product is about. Not enabling it in a GRC product would be embarrassing.
  enable_key_rotation = true

  # Long enough to recover from a mistaken destroy, short enough that a torn-down
  # portfolio project stops billing within a week.
  deletion_window_in_days = 7
}

resource "aws_kms_alias" "main" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.main.key_id
}

# --------------------------------------------------------------------------
# documents and index

resource "aws_s3_bucket" "documents" {
  bucket        = "${local.name}-${data.aws_caller_identity.current.account_id}"
  force_destroy = true # portfolio project: destroy must not stall on objects
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.main.arn
    }
    # Encrypts with one data key per bucket rather than per object. Fewer KMS
    # calls, and KMS requests are the part of this that actually costs money.
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Two policies in one: refuse plaintext uploads, and refuse anything not over
# TLS. The bucket default encrypts on write, but a client can override it, and
# "we encrypt at rest" is an attestation this product makes on a customer's
# behalf.
resource "aws_s3_bucket_policy" "documents" {
  bucket = aws_s3_bucket.documents.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyUnencryptedUploads"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.documents.arn}/*"
        Condition = {
          StringNotEquals = { "s3:x-amz-server-side-encryption" = "aws:kms" }
        }
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.documents.arn, "${aws_s3_bucket.documents.arn}/*"]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      }
    ]
  })
}

# Old versions and incomplete uploads bill forever otherwise. Versioning without
# a lifecycle rule is how a bucket quietly grows for years.
resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    id     = "expire-noncurrent-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# --------------------------------------------------------------------------
# job state and checkpoints

resource "aws_dynamodb_table" "jobs" {
  name = "${local.name}-jobs"
  # On-demand, not provisioned. Provisioned capacity bills per hour whether or
  # not anything runs, which breaks the under-$5/month rule for a service that
  # is idle almost all the time.
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "job_id"

  attribute {
    name = "job_id"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.main.arn
  }

  point_in_time_recovery {
    enabled = true
  }
}

resource "aws_dynamodb_table" "checkpoints" {
  name         = "${local.name}-checkpoints"
  billing_mode = "PAY_PER_REQUEST"

  # Composite key: one item per checkpoint, partitioned by thread. The thread id
  # is "{job_id}:{question_id}" (see MISTAKES entry 35) so one tenant's questions
  # cannot land in another's partition.
  hash_key  = "thread_id"
  range_key = "checkpoint_id"

  attribute {
    name = "thread_id"
    type = "S"
  }
  attribute {
    name = "checkpoint_id"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.main.arn
  }

  point_in_time_recovery {
    enabled = true
  }

  # Checkpoints hold questionnaire text and retrieved policy extracts. A run
  # abandoned mid-review should not keep customer content indefinitely.
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}
