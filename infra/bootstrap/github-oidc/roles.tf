resource "aws_iam_role" "github_dev_identity" {
  name = local.github_identity_role

  description = "Permissionless GitHub Actions OIDC role used to verify CloudDoc development identity federation."

  assume_role_policy   = data.aws_iam_policy_document.github_identity_assume_role.json
  max_session_duration = var.role_max_session_duration

  tags = merge(local.common_tags, {
    Name            = local.github_identity_role
    IdentityPurpose = "verification"
  })
}

resource "aws_iam_role" "github_dev_deploy_identity" {
  name = local.github_deploy_identity_role_name

  description = "Permissionless GitHub Actions OIDC role used to authenticate the exact CloudDoc Terraform deployment workflow and intentionally carries no permission policy."

  assume_role_policy   = data.aws_iam_policy_document.github_deploy_identity_assume_role.json
  max_session_duration = var.role_max_session_duration

  tags = merge(local.common_tags, {
    Name            = local.github_deploy_identity_role_name
    IdentityPurpose = "deployment"
  })
}