variable "aws_region" {
  description = "Region. Must match where Bedrock model access was granted."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name, used in resource names and tags."
  type        = string
  default     = "dev"
}

variable "project" {
  description = "Name prefix for every resource."
  type        = string
  default     = "grc-copilot"
}

variable "bedrock_model_id" {
  description = "Answering model. Cheapest that reliably drives a tool call -- see ADR-0004."
  type        = string
  default     = "amazon.nova-lite-v1:0"
}

variable "bedrock_embed_model_id" {
  description = "Embedding model. Changing it invalidates the index -- see ADR-0006."
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "api_key" {
  description = <<-EOT
    Shared key for the HTTP API. A shared key gives no identity and no
    per-tenant authorisation -- see docs/THREAT-MODEL.md T6. Passed via
    TF_VAR_api_key, never committed.
  EOT
  type        = string
  sensitive   = true
}

variable "log_retention_days" {
  description = "CloudWatch retention. Never 0 -- infinite retention is a silent cost leak."
  type        = number
  default     = 14
}

variable "monthly_budget_usd" {
  description = "Alarm threshold for estimated charges."
  type        = number
  default     = 5
}
