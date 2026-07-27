variable "aws_region" {
  description = "AWS Region where the CloudDoc Terraform state bucket will be provisioned."
  type        = string
  nullable    = false

  validation {
    condition     = length(trimspace(var.aws_region)) > 0
    error_message = "aws_region must not be blank."
  }
}

variable "project_name" {
  description = "Stable project identifier used in the account-scoped state bucket name and tags."
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

variable "noncurrent_version_retention_days" {
  description = "Number of days to retain noncurrent Terraform state object versions."
  type        = number
  default     = 365
  nullable    = false

  validation {
    condition = (
      var.noncurrent_version_retention_days >= 30 &&
      var.noncurrent_version_retention_days <= 3650 &&
      floor(var.noncurrent_version_retention_days) ==
      var.noncurrent_version_retention_days
    )
    error_message = "noncurrent_version_retention_days must be a whole number from 30 through 3650."
  }
}