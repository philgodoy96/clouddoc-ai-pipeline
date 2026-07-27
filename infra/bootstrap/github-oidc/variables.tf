variable "aws_region" {
  description = "AWS Region used by the provider while managing the global IAM trust resources."
  type        = string
  default     = "us-east-1"
  nullable    = false

  validation {
    condition     = length(trimspace(var.aws_region)) > 0
    error_message = "aws_region must not be blank."
  }
}

variable "project_name" {
  description = "Stable project identifier used in IAM resource names and tags."
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

variable "github_repository_owner" {
  description = "GitHub repository owner trusted by the AWS identity role."
  type        = string
  default     = "philgodoy96"
  nullable    = false

  validation {
    condition = (
      length(trimspace(var.github_repository_owner)) > 0 &&
      !strcontains(var.github_repository_owner, "/") &&
      !strcontains(var.github_repository_owner, "*")
    )
    error_message = "github_repository_owner must be a nonblank owner name without slashes or wildcards."
  }
}

variable "github_repository_name" {
  description = "GitHub repository name trusted by the AWS identity role."
  type        = string
  default     = "clouddoc-ai-pipeline"
  nullable    = false

  validation {
    condition = (
      length(trimspace(var.github_repository_name)) > 0 &&
      !strcontains(var.github_repository_name, "/") &&
      !strcontains(var.github_repository_name, "*")
    )
    error_message = "github_repository_name must be a nonblank repository name without slashes or wildcards."
  }
}

variable "github_repository_id" {
  description = "Immutable numeric GitHub repository ID trusted by AWS."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]{1,20}$", var.github_repository_id))
    error_message = "github_repository_id must contain only digits."
  }
}

variable "github_repository_owner_id" {
  description = "Immutable numeric GitHub repository owner ID trusted by AWS."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]{1,20}$", var.github_repository_owner_id))
    error_message = "github_repository_owner_id must contain only digits."
  }
}

variable "github_environment" {
  description = "GitHub Environment required by the identity verification workflow."
  type        = string
  default     = "dev"
  nullable    = false

  validation {
    condition     = var.github_environment == "dev"
    error_message = "github_environment must remain dev for the verification identity."
  }
}

variable "github_ref" {
  description = "Exact Git ref allowed to assume the identity verification role."
  type        = string
  default     = "refs/heads/main"
  nullable    = false

  validation {
    condition     = var.github_ref == "refs/heads/main"
    error_message = "github_ref must remain refs/heads/main."
  }
}

variable "github_identity_workflow_ref" {
  description = "Exact reusable workflow ref allowed to assume the identity verification role."
  type        = string
  default     = "philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-aws-identity.yml@refs/heads/main"
  nullable    = false

  validation {
    condition = var.github_identity_workflow_ref == (
      "${var.github_repository_owner}/${var.github_repository_name}/.github/workflows/reusable-aws-identity.yml@refs/heads/main"
    )
    error_message = "github_identity_workflow_ref must identify reusable-aws-identity.yml from the approved repository main branch."
  }
}

variable "role_max_session_duration" {
  description = "Maximum session duration for the permissionless GitHub identity verification role."
  type        = number
  default     = 3600
  nullable    = false

  validation {
    condition     = var.role_max_session_duration == 3600
    error_message = "role_max_session_duration must remain 3600 seconds."
  }
}