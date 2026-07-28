output "github_oidc_provider_arn" {
  description = "ARN of the GitHub Actions IAM OIDC provider."
  value       = aws_iam_openid_connect_provider.github_actions.arn
}

output "github_dev_identity_role_name" {
  description = "Name of the permissionless GitHub development identity role."
  value       = aws_iam_role.github_dev_identity.name
}

output "github_dev_identity_role_arn" {
  description = "ARN of the permissionless GitHub development identity role."
  value       = aws_iam_role.github_dev_identity.arn
}

output "github_dev_identity_role_max_session_duration" {
  description = "Maximum session duration configured for the GitHub development identity role."
  value       = aws_iam_role.github_dev_identity.max_session_duration
}

output "github_repository_identity" {
  description = "GitHub repository owner, name, repository ID, and owner ID trusted by the role."
  value = {
    repository          = local.github_repository
    repository_id       = var.github_repository_id
    repository_owner_id = var.github_repository_owner_id
  }
}

output "github_identity_workflow_ref" {
  description = "Exact reusable workflow reference trusted by the role."
  value       = var.github_identity_workflow_ref
}

output "github_trusted_workflow_refs" {
  description = "Exact reusable-workflow allowlist trusted by the GitHub identity role."
  value       = local.github_trusted_workflow_refs
}