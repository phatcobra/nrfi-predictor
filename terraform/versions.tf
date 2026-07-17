terraform {
  required_version = ">= 1.7.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Configure the S3 backend explicitly during terraform init. No state bucket,
  # account identifier, or workstation path is committed to this repository.
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_vpc" "default" {
  default = true
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
  common_tags = {
    Application = "NRFI-YRFI-Probability"
    Environment = var.environment
    ManagedBy   = "Terraform"
    Repository  = var.repository_slug
  }
}
