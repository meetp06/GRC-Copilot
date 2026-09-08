# Alarms, and a budget that tells you before the bill does.
#
# The cost alarm is the one that matters for a portfolio project. The most
# likely failure here is not an outage -- it is forgetting to run `tofu destroy`
# and finding out a month later.

resource "aws_sns_topic" "alerts" {
  name              = "${local.name}-alerts"
  kms_master_key_id = "alias/aws/sns"
}

# Subscribe by hand after apply. An email subscription in Terraform sits in
# state as "pending confirmation" forever and shows a permanent diff:
#   aws sns subscribe --topic-arn <arn> --protocol email --notification-endpoint you@example.com

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${local.name}-lambda-errors"
  alarm_description   = "The API is failing requests"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.api.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  # Missing data means no traffic, which is the normal state of this service.
  # The default treats it as breaching and pages about an idle system.
  treat_missing_data = "notBreaching"
  alarm_actions      = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "lambda_throttles" {
  alarm_name          = "${local.name}-lambda-throttles"
  alarm_description   = "Concurrency limit reached -- requests are being rejected"
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  dimensions          = { FunctionName = aws_lambda_function.api.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# Estimated charges are published to CloudWatch only in us-east-1, regardless of
# where the resources are.
resource "aws_cloudwatch_metric_alarm" "estimated_charges" {
  provider = aws.us_east_1

  alarm_name          = "${local.name}-estimated-charges"
  alarm_description   = "Account spend above the budget -- likely a forgotten deployment"
  namespace           = "AWS/Billing"
  metric_name         = "EstimatedCharges"
  dimensions          = { Currency = "USD" }
  statistic           = "Maximum"
  period              = 21600 # billing metrics update roughly every 6 hours
  evaluation_periods  = 1
  threshold           = var.monthly_budget_usd
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}
