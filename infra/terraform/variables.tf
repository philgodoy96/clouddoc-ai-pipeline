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

variable "expected_aws_account_id" {
  description = "Optional AWS account ID allowlist guard used by authenticated plan and apply operations."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.expected_aws_account_id == null ||
      can(regex("^[0-9]{12}$", var.expected_aws_account_id))
    )
    error_message = "expected_aws_account_id must be null or a 12-digit AWS account ID."
  }
}

variable "terraform_plan_role_arn" {
  description = "Optional IAM role ARN assumed by the AWS provider for plan-only authorization during authenticated execution. When null, the provider uses ambient AWS credentials so local execution remains compatible. This value identifies a role and is not a credential. When set, it must identify role/clouddoc-dev-terraform-plan."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.terraform_plan_role_arn == null ||
      can(regex(
        "^arn:(aws|aws-us-gov|aws-cn):iam::[0-9]{12}:role/clouddoc-dev-terraform-plan$",
        var.terraform_plan_role_arn,
      ))
    )
    error_message = "terraform_plan_role_arn must be null or an IAM role ARN for role/clouddoc-dev-terraform-plan using an accepted partition and a 12-digit account ID."
  }

  validation {
    condition = (
      var.terraform_plan_role_arn == null ||
      var.expected_aws_account_id == null ||
      can(regex(
        format(
          "^arn:(aws|aws-us-gov|aws-cn):iam::%s:role/clouddoc-dev-terraform-plan$",
          var.expected_aws_account_id,
        ),
        var.terraform_plan_role_arn,
      ))
    )
    error_message = "terraform_plan_role_arn account must match expected_aws_account_id when both values are set."
  }
}