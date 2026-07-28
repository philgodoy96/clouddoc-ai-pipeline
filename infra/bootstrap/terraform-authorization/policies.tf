resource "aws_iam_role_policy" "terraform_state_access" {
  name   = local.terraform_state_policy_name
  role   = aws_iam_role.terraform_state.id
  policy = data.aws_iam_policy_document.terraform_state_access.json
}

resource "aws_iam_role_policy" "terraform_plan_access" {
  name   = local.terraform_plan_policy_name
  role   = aws_iam_role.terraform_plan.id
  policy = data.aws_iam_policy_document.terraform_plan_access.json
}
