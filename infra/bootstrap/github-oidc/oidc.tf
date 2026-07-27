resource "aws_iam_openid_connect_provider" "github_actions" {
  url = local.github_oidc_url

  client_id_list = [
    local.github_oidc_audience,
  ]

  tags = merge(local.common_tags, {
    Name = "${var.project_name}-github-actions"
  })
}