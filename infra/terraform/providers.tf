locals {
  effective_provider_role_arn = (
    var.terraform_plan_role_arn != null
    ? var.terraform_plan_role_arn
    : var.terraform_apply_role_arn
  )
  effective_provider_session_name = (
    var.terraform_plan_role_arn != null
    ? "clouddoc-terraform-plan"
    : "clouddoc-terraform-apply"
  )
}

provider "aws" {
  region = var.aws_region

  allowed_account_ids = (
    var.expected_aws_account_id == null
    ? null
    : [var.expected_aws_account_id]
  )

  default_tags {
    tags = local.common_tags
  }

  dynamic "assume_role" {
    for_each = (
      local.effective_provider_role_arn == null
      ? []
      : [local.effective_provider_role_arn]
    )

    content {
      role_arn     = assume_role.value
      session_name = local.effective_provider_session_name
      duration     = "15m"
    }
  }
}
