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
      var.terraform_plan_role_arn == null
      ? []
      : [var.terraform_plan_role_arn]
    )

    content {
      role_arn     = assume_role.value
      session_name = "clouddoc-terraform-plan"
      duration     = "15m"
    }
  }
}
