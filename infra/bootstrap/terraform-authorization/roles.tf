resource "aws_iam_role" "terraform_state" {
  name                 = local.terraform_state_role_name
  description          = "Chained role that authorizes GitHub Actions to read and write only the CloudDoc development Terraform state and lock objects."
  assume_role_policy   = data.aws_iam_policy_document.terraform_state_assume_role.json
  max_session_duration = local.role_max_session_duration
  path                 = "/"

  tags = local.common_tags
}

resource "aws_iam_role" "terraform_plan" {
  name                 = local.terraform_plan_role_name
  description          = "Chained role that authorizes GitHub Actions to refresh CloudDoc development application resources during Terraform plan."
  assume_role_policy   = data.aws_iam_policy_document.terraform_plan_assume_role.json
  max_session_duration = local.role_max_session_duration
  path                 = "/"

  tags = local.common_tags
}

resource "aws_iam_role" "terraform_apply" {
  name                 = local.terraform_apply_role_name
  description          = "Chained role that authorizes controlled Terraform infrastructure mutation for the CloudDoc dev environment."
  assume_role_policy   = data.aws_iam_policy_document.terraform_apply_assume_role.json
  max_session_duration = local.role_max_session_duration
  path                 = "/"

  tags = local.common_tags
}
