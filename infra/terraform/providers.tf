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
}