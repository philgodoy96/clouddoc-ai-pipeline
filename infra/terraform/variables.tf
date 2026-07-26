variable "aws_region" {
  description = "AWS Region where CloudDoc resources will be provisioned."
  type        = string
  nullable    = false

  validation {
    condition     = length(trimspace(var.aws_region)) > 0
    error_message = "aws_region must not be blank."
  }
}

variable "project_name" {
  description = "Stable project identifier used in resource names and tags."
  type        = string
  default     = "clouddoc"
  nullable    = false

  validation {
    condition = (
      length(var.project_name) >= 3 &&
      length(var.project_name) <= 32 &&
      can(regex("^[a-z][a-z0-9-]*[a-z0-9]$", var.project_name))
    )
    error_message = "project_name must contain 3 to 32 lowercase letters, numbers, or hyphens and must start with a letter."
  }
}

variable "environment" {
  description = "Deployment environment represented in resource names and tags."
  type        = string
  default     = "dev"
  nullable    = false

  validation {
    condition = contains(
      [
        "dev",
        "staging",
        "prod",
      ],
      var.environment,
    )
    error_message = "environment must be one of: dev, staging, prod."
  }
}