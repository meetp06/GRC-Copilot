# One role, and every action in it named explicitly.
#
# CLAUDE.md: "IAM policies are least-privilege. If you need a new permission,
# name the exact action." Week 1 already paid for that rule twice -- MISTAKES
# entries 5 and 9 are both an AWS denial that named the action while the
# resource ARN was the actual problem.
#
# Nothing here uses Action = "*" or a bare Resource = "*" except where the API
# genuinely has no resource to scope to.

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api" {
  name               = "${local.name}-api"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "api" {
  # --- logs ---
  statement {
    sid    = "WriteOwnLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    # Scoped to this function's log group. CreateLogGroup is deliberately absent:
    # the group is created by Terraform below, so the function does not need to.
    resources = ["${aws_cloudwatch_log_group.api.arn}:*"]
  }

  # --- models ---
  statement {
    sid    = "InvokeTheTwoModelsWeUse"
    effect = "Allow"
    actions = [
      "bedrock:InvokeModel",
    ]
    # Two exact ARNs, not amazon.*. Week 2 lost time to a policy that allowed
    # InvokeModel on amazon.nova-* while the call was for Titan, and the error
    # named the action rather than the resource. Being explicit means the next
    # denial says exactly which model is missing.
    resources = [
      "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.bedrock_model_id}",
      "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.bedrock_embed_model_id}",
    ]
  }

  # --- documents and index ---
  statement {
    sid       = "ReadTheCorpusAndIndex"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [aws_s3_bucket.documents.arn, "${aws_s3_bucket.documents.arn}/*"]
  }
  # No s3:PutObject and no s3:DeleteObject. The request path reads the index and
  # never writes it -- ingestion runs elsewhere (ADR-0012). A compromised API
  # cannot alter the policy corpus its answers are drawn from.

  # --- job state ---
  statement {
    sid    = "ReadAndWriteJobState"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:BatchGetItem",
      "dynamodb:BatchWriteItem",
    ]
    resources = [
      aws_dynamodb_table.jobs.arn,
      aws_dynamodb_table.checkpoints.arn,
    ]
  }
  # dynamodb:DeleteTable, CreateTable and UpdateTable are absent. The function
  # uses tables; it does not manage them.

  # --- encryption ---
  statement {
    sid    = "UseTheProjectKey"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:GenerateDataKey",
    ]
    resources = [aws_kms_key.main.arn]
    # Only through S3 and DynamoDB, so a stolen role credential cannot use the
    # key to decrypt anything else that happens to be encrypted with it.
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values = [
        "s3.${var.aws_region}.amazonaws.com",
        "dynamodb.${var.aws_region}.amazonaws.com",
        # Secrets Manager decrypts the API key on the function's behalf. Leaving
        # it out meant the Lambda could reach the secret and not read it, and
        # the error said only "Access to KMS is not allowed" -- naming neither
        # the service nor the condition that refused it.
        "secretsmanager.${var.aws_region}.amazonaws.com",
      ]
    }
  }

  # --- secrets ---
  statement {
    sid       = "ReadTheApiKey"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.api_key.arn]
  }
}

resource "aws_iam_role_policy" "api" {
  name   = "${local.name}-api"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

# --------------------------------------------------------------------------
# the API key

# Secrets Manager rather than a Lambda environment variable. An environment
# variable is visible to anyone with lambda:GetFunctionConfiguration, appears in
# the console, and would sit in Terraform state in plaintext.
resource "aws_secretsmanager_secret" "api_key" {
  name                    = "${local.name}/api-key"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = 0 # portfolio project: destroy should actually destroy
}

resource "aws_secretsmanager_secret_version" "api_key" {
  secret_id     = aws_secretsmanager_secret.api_key.id
  secret_string = var.api_key
}
