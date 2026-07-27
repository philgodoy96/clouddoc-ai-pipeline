locals {
  github_oidc_url      = "https://token.actions.githubusercontent.com"
  github_oidc_host     = "token.actions.githubusercontent.com"
  github_oidc_audience = "sts.amazonaws.com"
  github_repository    = "${var.github_repository_owner}/${var.github_repository_name}"
  github_identity_role = "${var.project_name}-${var.github_environment}-github-identity"

  common_tags = {
    Project     = var.project_name
    ManagedBy   = "terraform"
    Component   = "github-oidc"
    Scope       = "account"
    Environment = var.github_environment
  }
}