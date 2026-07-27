data "aws_iam_policy_document" "github_identity_assume_role" {
  statement {
    sid    = "AllowApprovedGitHubIdentityWorkflow"
    effect = "Allow"

    actions = [
      "sts:AssumeRoleWithWebIdentity",
    ]

    principals {
      type = "Federated"

      identifiers = [
        aws_iam_openid_connect_provider.github_actions.arn,
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.github_oidc_host}:aud"

      values = [
        local.github_oidc_audience,
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.github_oidc_host}:repository"

      values = [
        local.github_repository,
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.github_oidc_host}:repository_id"

      values = [
        var.github_repository_id,
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.github_oidc_host}:repository_owner_id"

      values = [
        var.github_repository_owner_id,
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.github_oidc_host}:ref"

      values = [
        var.github_ref,
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.github_oidc_host}:environment"

      values = [
        var.github_environment,
      ]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.github_oidc_host}:job_workflow_ref"

      values = [
        var.github_identity_workflow_ref,
      ]
    }
  }
}