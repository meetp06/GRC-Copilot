# OpenTofu rather than Terraform. HashiCorp moved Terraform to the Business
# Source Licence in 2023 and it left homebrew-core; OpenTofu is the Linux
# Foundation fork of 1.5.x, same HCL, same providers, `tofu` instead of
# `terraform`. See ADR-0016.

terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # Pinned to a minor. A provider upgrade can change a resource's default
      # and produce a plan that destroys and recreates something -- which for a
      # DynamoDB table means losing every job and checkpoint in it.
      version = "~> 5.70"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # State stays local, deliberately. An S3 backend needs a bucket and a lock
  # table that exist before the first apply, which is a bootstrap problem worth
  # solving only when more than one person runs this. terraform.tfstate is
  # gitignored: it contains resource ids and can contain secrets.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "grc-copilot"
      ManagedBy   = "opentofu"
      Environment = var.environment
      # Every resource carries this so `tofu destroy` missing something is
      # findable in the console with one filter.
      CostCentre = "portfolio"
    }
  }
}
