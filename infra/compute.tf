# Lambda behind API Gateway. Idle cost zero.
#
#   API Gateway (HTTP API) ─▶ Lambda ─▶ Bedrock
#                                    ↘ S3, DynamoDB
#
# Not ECS or EC2: both bill per hour whether or not a request arrives, and this
# service is idle almost all the time. HTTP API rather than REST API -- about a
# third the price and this needs none of what REST API adds.
#
# The 15-minute Lambda ceiling is a real constraint on this product. A
# 200-question run takes about four minutes, so a 500-question one would not
# finish. The row cap in the API is set below that; a genuinely large
# questionnaire needs Step Functions or a queue, which is noted in ADR-0017
# rather than pretended away.

resource "aws_cloudwatch_log_group" "api" {
  name = "/aws/lambda/${local.name}-api"
  # Never unset. Infinite retention is a cost leak that grows quietly, and these
  # logs may contain fragments of customer questionnaires.
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.logs.arn
}

# CloudWatch needs its own key policy, so it cannot share the S3/DynamoDB key
# without widening that key's policy to a second service.
resource "aws_kms_key" "logs" {
  description             = "GRC Copilot log encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 7

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountRoot"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "CloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${var.aws_region}.amazonaws.com" }
        Action = [
          "kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*",
          "kms:GenerateDataKey*", "kms:Describe*"
        ]
        Resource = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:*"
          }
        }
      }
    ]
  })
}

# Built by scripts/build_lambda.sh, which installs only the request-path
# dependencies. Measured: 79 MB with dagster, pdfplumber and mcp excluded,
# against Lambda's 250 MB unzipped limit. Those three are ingestion and
# developer tooling and have no business in a request path.
data "archive_file" "api" {
  type        = "zip"
  source_dir  = "${path.module}/../build/lambda"
  output_path = "${path.module}/../build/api.zip"
}

resource "aws_lambda_function" "api" {
  function_name = "${local.name}-api"
  role          = aws_iam_role.api.arn

  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256

  runtime = "python3.11"
  handler = "lambda_handler.handler"

  # 1024 MB is not about memory. Lambda scales CPU with memory, and numpy's
  # matrix multiply over the index is CPU-bound -- at 512 MB the same request
  # takes roughly twice as long, so the cheaper setting costs more per request.
  memory_size = 1024

  # Under the 15-minute ceiling and above the p95 for a single question (3.3s
  # measured). A batch run is capped at 500 questions in the API for the same
  # reason.
  timeout = 300

  environment {
    variables = {
      AWS_REGION_NAME        = var.aws_region
      BEDROCK_MODEL_ID       = var.bedrock_model_id
      BEDROCK_EMBED_MODEL_ID = var.bedrock_embed_model_id
      DOCUMENTS_BUCKET       = aws_s3_bucket.documents.id
      JOBS_TABLE             = aws_dynamodb_table.jobs.name
      CHECKPOINTS_TABLE      = aws_dynamodb_table.checkpoints.name
      API_KEY_SECRET_ARN     = aws_secretsmanager_secret.api_key.arn
      # The API key itself is NOT here. An environment variable is readable by
      # anyone with lambda:GetFunctionConfiguration and sits in Terraform state
      # in plaintext.

      # langsmith ships with langgraph and sends full prompts to LangChain's
      # cloud when tracing is on. The prompts contain customer policy text by
      # design -- see ADR-0009 and THREAT-MODEL T3.
      LANGCHAIN_TRACING_V2 = "false"
      LANGSMITH_TRACING    = "false"
    }
  }

  depends_on = [aws_cloudwatch_log_group.api]
}

# --------------------------------------------------------------------------
# the front door

resource "aws_apigatewayv2_api" "main" {
  name          = "${local.name}-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "proxy" {
  api_id    = aws_apigatewayv2_api.main.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  # Rate limiting, which THREAT-MODEL T4 listed as missing. A burst of 20 and 10
  # per second is far above real use and far below what would run up a bill.
  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn
    # Deliberately no request or response body. These logs would otherwise hold
    # questionnaire text and answers -- CLAUDE.md's rule about not logging
    # documents applies here as much as to application logs.
    format = jsonencode({
      requestId  = "$context.requestId"
      httpMethod = "$context.httpMethod"
      path       = "$context.path"
      status     = "$context.status"
      latency    = "$context.responseLatency"
      ip         = "$context.identity.sourceIp"
    })
  }
}

resource "aws_cloudwatch_log_group" "access" {
  name              = "/aws/apigateway/${local.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}
