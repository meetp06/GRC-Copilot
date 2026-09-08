output "api_url" {
  description = "Base URL. Send X-API-Key with every request except /health."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "documents_bucket" {
  description = "Upload the parsed corpus and the vector index here."
  value       = aws_s3_bucket.documents.id
}

output "alerts_topic_arn" {
  description = "Subscribe to this to receive the cost and error alarms."
  value       = aws_sns_topic.alerts.arn
}

output "destroy_reminder" {
  description = "Read this."
  value       = "Idle cost is ~$2/month, almost all of it the two KMS keys. Run `tofu destroy` when you are done demonstrating."
}

output "smoke_test" {
  description = "Confirm the deployment works."
  value       = "curl ${aws_apigatewayv2_stage.default.invoke_url}/health"
}
