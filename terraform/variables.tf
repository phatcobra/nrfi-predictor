variable "aws_region" {
  description = "Approved AWS region. Supply explicitly; there is no deployment default."
  type        = string

  validation {
    condition     = can(regex("^[a-z]{2}-[a-z]+-[0-9]+$", var.aws_region))
    error_message = "aws_region must be an AWS region identifier such as us-east-2."
  }
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

variable "project_name" {
  description = "Resource-name prefix."
  type        = string
  default     = "nrfi-probability"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,30}$", var.project_name))
    error_message = "project_name must contain 3-30 lowercase letters, digits, or hyphens."
  }
}

variable "repository_slug" {
  description = "GitHub owner/repository used for traceability tags."
  type        = string
  default     = "phatcobra/nrfi-predictor"
}

variable "private_subnet_cidr" {
  description = "Approved non-overlapping CIDR for the single-AZ private Batch subnet."
  type        = string
  default     = "172.31.48.0/24"

  validation {
    condition     = can(cidrhost(var.private_subnet_cidr, 1))
    error_message = "private_subnet_cidr must be a valid IPv4 CIDR."
  }
}

variable "private_subnet_availability_zone" {
  description = "Approved availability zone for the cost-bounded private Batch subnet."
  type        = string
  default     = "us-east-2a"

  validation {
    condition     = startswith(var.private_subnet_availability_zone, var.aws_region)
    error_message = "private_subnet_availability_zone must belong to aws_region."
  }
}

variable "enable_batch" {
  description = "Create the scale-to-zero Batch environment after networking is verified."
  type        = bool
  default     = false
}

variable "batch_max_vcpus" {
  description = "Hard ceiling for the Batch Fargate compute environment."
  type        = number
  default     = 2

  validation {
    condition     = var.batch_max_vcpus >= 1 && var.batch_max_vcpus <= 4
    error_message = "batch_max_vcpus must be between 1 and 4."
  }
}

variable "batch_image_tag" {
  description = "Immutable release tag for the deterministic Python 3.11 container."
  type        = string
  default     = "baseline-not-published"
}

variable "batch_job_vcpus" {
  description = "vCPU allocation for the baseline replay job."
  type        = number
  default     = 2
}

variable "batch_job_memory_mib" {
  description = "Memory allocation for the baseline replay job."
  type        = number
  default     = 4096
}

variable "operational_log_retention_days" {
  description = "Retention for operational logs that are not immutable model evidence."
  type        = number
  default     = 30

  validation {
    condition = contains(
      [1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365],
      var.operational_log_retention_days,
    )
    error_message = "operational_log_retention_days must be supported by CloudWatch Logs."
  }
}

variable "evidence_retention_days" {
  description = "Governance retention for immutable evidence and prediction audits."
  type        = number
  default     = 365

  validation {
    condition     = var.evidence_retention_days >= 365
    error_message = "Evidence retention cannot be shorter than 365 days."
  }
}

variable "holdout_retention_days" {
  description = "Governance retention for the separately protected locked holdout."
  type        = number
  default     = 365

  validation {
    condition     = var.holdout_retention_days >= 365
    error_message = "Holdout retention cannot be shorter than 365 days."
  }
}

variable "enable_budget" {
  description = "Create the mandatory monthly budget only after amount and email approval."
  type        = bool
  default     = false
}

variable "monthly_budget_usd" {
  description = "Approved maximum monthly AWS budget in USD. Required when enable_budget is true."
  type        = number
  default     = null
  nullable    = true
}

variable "budget_notification_email" {
  description = "Approved email for budget notifications. Required when enable_budget is true."
  type        = string
  default     = null
  nullable    = true
  sensitive   = true
}
