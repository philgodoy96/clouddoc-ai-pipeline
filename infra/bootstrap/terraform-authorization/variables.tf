variable "aws_account_id" {
  description = "Twelve-digit AWS account ID that owns the CloudDoc development Terraform authorization roles."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be exactly 12 decimal digits."
  }
}

variable "aws_region" {
  description = "AWS Region used by the provider while managing the development Terraform authorization roles."
  type        = string
  default     = "us-east-1"
  nullable    = false

  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "aws_region must remain us-east-1."
  }
}

variable "environment" {
  description = "Deployment environment represented by the Terraform authorization roles."
  type        = string
  default     = "dev"
  nullable    = false

  validation {
    condition     = var.environment == "dev"
    error_message = "environment must remain dev for this authorization bootstrap."
  }
}

variable "project_name" {
  description = "Stable project identifier used in IAM resource names and tags."
  type        = string
  default     = "clouddoc"
  nullable    = false

  validation {
    condition     = var.project_name == "clouddoc"
    error_message = "project_name must remain clouddoc."
  }
}

variable "terraform_state_bucket_name" {
  description = "Exact account-scoped S3 bucket that stores the CloudDoc development Terraform state object."
  type        = string
  nullable    = false

  validation {
    condition = (
      var.terraform_state_bucket_name ==
      "clouddoc-${var.aws_account_id}-terraform-state"
    )
    error_message = "terraform_state_bucket_name must equal clouddoc-<aws_account_id>-terraform-state."
  }
}

variable "terraform_state_key" {
  description = "Exact object key of the CloudDoc development Terraform state."
  type        = string
  default     = "clouddoc/dev/terraform.tfstate"
  nullable    = false

  validation {
    condition = (
      var.terraform_state_key == "clouddoc/dev/terraform.tfstate" &&
      !startswith(var.terraform_state_key, "/") &&
      !strcontains(var.terraform_state_key, "..") &&
      !strcontains(var.terraform_state_key, "*")
    )
    error_message = "terraform_state_key must remain clouddoc/dev/terraform.tfstate without leading slashes, parent traversal, or wildcards."
  }
}

variable "github_identity_role_name" {
  description = "Exact name of the permissionless GitHub OIDC identity role allowed to assume the state and plan roles."
  type        = string
  default     = "clouddoc-dev-github-identity"
  nullable    = false

  validation {
    condition     = var.github_identity_role_name == "clouddoc-dev-github-identity"
    error_message = "github_identity_role_name must remain clouddoc-dev-github-identity."
  }
}
