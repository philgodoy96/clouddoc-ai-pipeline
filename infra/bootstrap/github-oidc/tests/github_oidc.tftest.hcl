mock_provider "aws" {
  override_during = plan

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

variables {
  aws_region                           = "us-east-1"
  project_name                         = "clouddoc"
  github_repository_owner              = "philgodoy96"
  github_repository_name               = "clouddoc-ai-pipeline"
  github_repository_id                 = "987654321"
  github_repository_owner_id           = "12345678"
  github_environment                   = "dev"
  github_deploy_environment            = "dev-deploy"
  github_ref                           = "refs/heads/main"
  github_identity_workflow_ref         = "philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-aws-identity.yml@refs/heads/main"
  github_terraform_plan_workflow_ref   = "philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-terraform-plan.yml@refs/heads/main"
  github_terraform_deploy_workflow_ref = "philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-terraform-deploy.yml@refs/heads/main"
  role_max_session_duration            = 3600
}

override_resource {
  target          = aws_iam_openid_connect_provider.github_actions
  override_during = plan

  values = {
    arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
  }
}

override_resource {
  target          = aws_iam_role.github_dev_identity
  override_during = plan

  values = {
    arn       = "arn:aws:iam::123456789012:role/clouddoc-dev-github-identity"
    unique_id = "AROATESTGITHUBIDENTITY"
  }
}

override_resource {
  target          = aws_iam_role.github_dev_deploy_identity
  override_during = plan

  values = {
    arn       = "arn:aws:iam::123456789012:role/clouddoc-dev-github-deploy-identity"
    unique_id = "AROATESTGITHUBDEPLOY"
  }
}

run "github_oidc_provider_contract" {
  command = plan

  assert {
    condition = (
      local.github_oidc_url == "https://token.actions.githubusercontent.com" &&
      local.github_oidc_host == "token.actions.githubusercontent.com" &&
      local.github_oidc_audience == "sts.amazonaws.com"
    )
    error_message = "The GitHub OIDC issuer, host, and STS audience must remain canonical."
  }

  assert {
    condition = (
      aws_iam_openid_connect_provider.github_actions.url ==
      local.github_oidc_url &&
      toset(
        aws_iam_openid_connect_provider.github_actions.client_id_list
      ) == toset([local.github_oidc_audience])
    )
    error_message = "The IAM OIDC provider must trust only the GitHub issuer and AWS STS audience."
  }

  assert {
    condition = (
      length([
        aws_iam_role.github_dev_identity.name,
        aws_iam_role.github_dev_deploy_identity.name,
      ]) == 2 &&
      aws_iam_role.github_dev_identity.name !=
      aws_iam_role.github_dev_deploy_identity.name
    )
    error_message = "The root must own exactly two permissionless GitHub identity roles."
  }

  assert {
    condition = (
      aws_iam_openid_connect_provider.github_actions.tags["Name"] ==
      "clouddoc-github-actions" &&
      aws_iam_openid_connect_provider.github_actions.tags["Project"] ==
      "clouddoc" &&
      aws_iam_openid_connect_provider.github_actions.tags["Component"] ==
      "github-oidc" &&
      aws_iam_openid_connect_provider.github_actions.tags["Scope"] ==
      "account" &&
      aws_iam_openid_connect_provider.github_actions.tags["Environment"] ==
      "dev"
    )
    error_message = "The GitHub OIDC provider must retain the approved account-scoped tags."
  }
}

run "github_identity_trust_contract" {
  command = plan

  assert {
    condition = (
      var.github_identity_workflow_ref ==
      "philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-aws-identity.yml@refs/heads/main" &&
      var.github_terraform_plan_workflow_ref ==
      "philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-terraform-plan.yml@refs/heads/main" &&
      var.github_identity_workflow_ref !=
      var.github_terraform_plan_workflow_ref
    )
    error_message = "Both approved reusable workflow refs must be exact, distinct, and pinned to main."
  }

  assert {
    condition = (
      length(local.github_trusted_workflow_refs) == 2 &&
      local.github_trusted_workflow_refs == sort([
        "philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-aws-identity.yml@refs/heads/main",
        "philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-terraform-plan.yml@refs/heads/main",
      ]) &&
      alltrue([
        for value in local.github_trusted_workflow_refs :
        endswith(value, "@refs/heads/main")
      ]) &&
      alltrue([
        for value in local.github_trusted_workflow_refs :
        !strcontains(value, "*") &&
        !strcontains(value, "?") &&
        !strcontains(value, "refs/pull/") &&
        !strcontains(value, "refs/tags/")
      ])
    )
    error_message = "The trusted workflow allowlist must be exactly two deterministic main-branch refs without wildcards, pull requests, or tags."
  }

  assert {
    condition = (
      length(
        data.aws_iam_policy_document.github_identity_assume_role.statement
      ) == 1 &&
      one(
        data.aws_iam_policy_document.github_identity_assume_role.statement
      ).sid == "AllowApprovedGitHubIdentityWorkflow" &&
      one(
        data.aws_iam_policy_document.github_identity_assume_role.statement
      ).effect == "Allow" &&
      toset(
        one(
          data.aws_iam_policy_document.github_identity_assume_role.statement
        ).actions
      ) == toset(["sts:AssumeRoleWithWebIdentity"])
    )
    error_message = "The trust policy must contain one allow statement for AssumeRoleWithWebIdentity only."
  }

  assert {
    condition = (
      length(
        one(
          data.aws_iam_policy_document.github_identity_assume_role.statement
        ).principals
      ) == 1 &&
      one(
        one(
          data.aws_iam_policy_document.github_identity_assume_role.statement
        ).principals
      ).type == "Federated" &&
      toset(
        one(
          one(
            data.aws_iam_policy_document.github_identity_assume_role.statement
          ).principals
        ).identifiers
        ) == toset([
          aws_iam_openid_connect_provider.github_actions.arn,
      ])
    )
    error_message = "The role must trust only the GitHub Actions IAM OIDC provider created by this root."
  }

  assert {
    condition = (
      length(
        one(
          data.aws_iam_policy_document.github_identity_assume_role.statement
        ).condition
      ) == 8 &&
      alltrue([
        for condition in one(
          data.aws_iam_policy_document.github_identity_assume_role.statement
        ).condition :
        condition.test == "StringEquals"
      ])
    )
    error_message = "The trust policy must use exactly eight StringEquals conditions."
  }

  assert {
    condition = alltrue([
      for expected in [
        {
          variable = "token.actions.githubusercontent.com:aud"
          values   = toset(["sts.amazonaws.com"])
        },
        {
          variable = "token.actions.githubusercontent.com:sub"
          values = toset([
            "repo:philgodoy96@12345678/clouddoc-ai-pipeline@987654321:environment:dev",
          ])
        },
        {
          variable = "token.actions.githubusercontent.com:repository"
          values   = toset(["philgodoy96/clouddoc-ai-pipeline"])
        },
        {
          variable = "token.actions.githubusercontent.com:repository_id"
          values   = toset(["987654321"])
        },
        {
          variable = "token.actions.githubusercontent.com:repository_owner_id"
          values   = toset(["12345678"])
        },
        {
          variable = "token.actions.githubusercontent.com:ref"
          values   = toset(["refs/heads/main"])
        },
        {
          variable = "token.actions.githubusercontent.com:environment"
          values   = toset(["dev"])
        },
        {
          variable = "token.actions.githubusercontent.com:job_workflow_ref"
          values = toset([
            "philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-aws-identity.yml@refs/heads/main",
            "philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-terraform-plan.yml@refs/heads/main",
          ])
        },
        ] : length([
          for actual in one(
            data.aws_iam_policy_document.github_identity_assume_role.statement
          ).condition : actual
          if(
            actual.variable == expected.variable &&
            actual.test == "StringEquals" &&
            toset(actual.values) == expected.values
          )
      ]) == 1
    ])
    error_message = "Every approved GitHub OIDC claim must have one exact reviewed value set."
  }

  assert {
    condition = (
      length([
        for condition in one(
          data.aws_iam_policy_document.github_identity_assume_role.statement
        ).condition : condition
        if condition.variable == "token.actions.githubusercontent.com:job_workflow_ref"
      ]) == 1 &&
      length(
        one([
          for condition in one(
            data.aws_iam_policy_document.github_identity_assume_role.statement
          ).condition : condition.values
          if condition.variable == "token.actions.githubusercontent.com:job_workflow_ref"
        ])
      ) == 2 &&
      toset(
        one([
          for condition in one(
            data.aws_iam_policy_document.github_identity_assume_role.statement
          ).condition : condition.values
          if condition.variable == "token.actions.githubusercontent.com:job_workflow_ref"
        ])
      ) == toset(local.github_trusted_workflow_refs)
    )
    error_message = "job_workflow_ref must appear once with exactly the two trusted workflow refs."
  }

  assert {
    condition = (
      length([
        for value in flatten([
          for condition in one(
            data.aws_iam_policy_document.github_identity_assume_role.statement
          ).condition : condition.values
        ]) : value
        if strcontains(value, "*") || strcontains(value, "?")
      ]) == 0
    )
    error_message = "The GitHub OIDC trust policy must not contain wildcard claim values."
  }
}

run "github_identity_role_safety_contract" {
  command = plan

  assert {
    condition = (
      aws_iam_role.github_dev_identity.name ==
      "clouddoc-dev-github-identity" &&
      aws_iam_role.github_dev_identity.max_session_duration == 3600
    )
    error_message = "The permissionless identity role must retain its canonical name and maximum session duration."
  }

  assert {
    condition = (
      aws_iam_role.github_dev_identity.description ==
      "Permissionless GitHub Actions OIDC role used to verify CloudDoc development identity federation."
    )
    error_message = "The role description must preserve its identity-verification purpose."
  }

  assert {
    condition = (
      aws_iam_role.github_dev_identity.tags["Name"] ==
      "clouddoc-dev-github-identity" &&
      aws_iam_role.github_dev_identity.tags["IdentityPurpose"] ==
      "verification" &&
      aws_iam_role.github_dev_identity.tags["Project"] ==
      "clouddoc" &&
      aws_iam_role.github_dev_identity.tags["Component"] ==
      "github-oidc" &&
      aws_iam_role.github_dev_identity.tags["Environment"] ==
      "dev"
    )
    error_message = "The identity role must retain the approved verification and ownership tags."
  }
}

run "github_deploy_identity_trust_contract" {
  command = plan

  assert {
    condition = (
      var.github_deploy_environment == "dev-deploy" &&
      var.github_terraform_deploy_workflow_ref ==
      "philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-terraform-deploy.yml@refs/heads/main"
    )
    error_message = "The deployment environment and reusable workflow ref must remain exact."
  }

  assert {
    condition = (
      length(
        data.aws_iam_policy_document.github_deploy_identity_assume_role.statement
      ) == 1 &&
      one(
        data.aws_iam_policy_document.github_deploy_identity_assume_role.statement
      ).sid == "AllowApprovedGitHubDeployWorkflow" &&
      one(
        data.aws_iam_policy_document.github_deploy_identity_assume_role.statement
      ).effect == "Allow" &&
      toset(
        one(
          data.aws_iam_policy_document.github_deploy_identity_assume_role.statement
        ).actions
      ) == toset(["sts:AssumeRoleWithWebIdentity"])
    )
    error_message = "The deployment trust policy must contain one allow statement for AssumeRoleWithWebIdentity only."
  }

  assert {
    condition = (
      length(
        one(
          data.aws_iam_policy_document.github_deploy_identity_assume_role.statement
        ).principals
      ) == 1 &&
      one(
        one(
          data.aws_iam_policy_document.github_deploy_identity_assume_role.statement
        ).principals
      ).type == "Federated" &&
      toset(
        one(
          one(
            data.aws_iam_policy_document.github_deploy_identity_assume_role.statement
          ).principals
        ).identifiers
        ) == toset([
          aws_iam_openid_connect_provider.github_actions.arn,
      ])
    )
    error_message = "The deployment role must trust only the GitHub Actions IAM OIDC provider created by this root."
  }

  assert {
    condition = (
      length(
        one(
          data.aws_iam_policy_document.github_deploy_identity_assume_role.statement
        ).condition
      ) == 8 &&
      alltrue([
        for condition in one(
          data.aws_iam_policy_document.github_deploy_identity_assume_role.statement
        ).condition :
        condition.test == "StringEquals"
      ])
    )
    error_message = "The deployment trust policy must use exactly eight StringEquals conditions."
  }

  assert {
    condition = alltrue([
      for expected in [
        {
          variable = "token.actions.githubusercontent.com:aud"
          values   = toset(["sts.amazonaws.com"])
        },
        {
          variable = "token.actions.githubusercontent.com:sub"
          values = toset([
            "repo:philgodoy96@12345678/clouddoc-ai-pipeline@987654321:environment:dev-deploy",
          ])
        },
        {
          variable = "token.actions.githubusercontent.com:repository"
          values   = toset(["philgodoy96/clouddoc-ai-pipeline"])
        },
        {
          variable = "token.actions.githubusercontent.com:repository_id"
          values   = toset(["987654321"])
        },
        {
          variable = "token.actions.githubusercontent.com:repository_owner_id"
          values   = toset(["12345678"])
        },
        {
          variable = "token.actions.githubusercontent.com:ref"
          values   = toset(["refs/heads/main"])
        },
        {
          variable = "token.actions.githubusercontent.com:environment"
          values   = toset(["dev-deploy"])
        },
        {
          variable = "token.actions.githubusercontent.com:job_workflow_ref"
          values = toset([
            "philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-terraform-deploy.yml@refs/heads/main",
          ])
        },
        ] : length([
          for actual in one(
            data.aws_iam_policy_document.github_deploy_identity_assume_role.statement
          ).condition : actual
          if(
            actual.variable == expected.variable &&
            actual.test == "StringEquals" &&
            toset(actual.values) == expected.values
          )
      ]) == 1
    ])
    error_message = "Every approved deployment GitHub OIDC claim must have one exact reviewed value set."
  }

  assert {
    condition = (
      length([
        for condition in one(
          data.aws_iam_policy_document.github_deploy_identity_assume_role.statement
        ).condition : condition
        if condition.variable == "token.actions.githubusercontent.com:job_workflow_ref"
      ]) == 1 &&
      length(
        one([
          for condition in one(
            data.aws_iam_policy_document.github_deploy_identity_assume_role.statement
          ).condition : condition.values
          if condition.variable == "token.actions.githubusercontent.com:job_workflow_ref"
        ])
      ) == 1 &&
      one(
        one([
          for condition in one(
            data.aws_iam_policy_document.github_deploy_identity_assume_role.statement
          ).condition : condition.values
          if condition.variable == "token.actions.githubusercontent.com:job_workflow_ref"
        ])
      ) == var.github_terraform_deploy_workflow_ref
    )
    error_message = "The deployment job_workflow_ref claim must appear once with exactly one trusted workflow ref."
  }

  assert {
    condition = (
      length([
        for value in flatten([
          for condition in one(
            data.aws_iam_policy_document.github_deploy_identity_assume_role.statement
          ).condition : condition.values
        ]) : value
        if(
          strcontains(value, "*") ||
          strcontains(value, "?") ||
          strcontains(value, "refs/pull/") ||
          strcontains(value, "refs/tags/") ||
          value == var.github_identity_workflow_ref ||
          value == var.github_terraform_plan_workflow_ref
        )
      ]) == 0
    )
    error_message = "The deployment trust must exclude wildcards, pull requests, tags, and the existing identity workflow refs."
  }
}

run "github_deploy_identity_role_safety_contract" {
  command = plan

  assert {
    condition = (
      aws_iam_role.github_dev_deploy_identity.name ==
      "clouddoc-dev-github-deploy-identity" &&
      aws_iam_role.github_dev_deploy_identity.max_session_duration == 3600
    )
    error_message = "The deployment identity role must retain its canonical name and approved maximum session duration."
  }

  assert {
    condition = (
      aws_iam_role.github_dev_deploy_identity.description ==
      "Permissionless GitHub Actions OIDC role used to authenticate the exact CloudDoc Terraform deployment workflow and intentionally carries no permission policy."
    )
    error_message = "The deployment role description must preserve its authentication-only purpose."
  }

  assert {
    condition = (
      aws_iam_role.github_dev_deploy_identity.tags["Name"] ==
      "clouddoc-dev-github-deploy-identity" &&
      aws_iam_role.github_dev_deploy_identity.tags["IdentityPurpose"] ==
      "deployment" &&
      aws_iam_role.github_dev_deploy_identity.tags["Project"] ==
      "clouddoc" &&
      aws_iam_role.github_dev_deploy_identity.tags["Component"] ==
      "github-oidc" &&
      aws_iam_role.github_dev_deploy_identity.tags["Environment"] ==
      "dev"
    )
    error_message = "The deployment identity role must retain the approved deployment and ownership tags."
  }
}

run "github_identity_outputs_contract" {
  command = plan

  assert {
    condition = (
      output.github_oidc_provider_arn ==
      aws_iam_openid_connect_provider.github_actions.arn &&
      output.github_dev_identity_role_name ==
      aws_iam_role.github_dev_identity.name &&
      output.github_dev_identity_role_arn ==
      aws_iam_role.github_dev_identity.arn &&
      output.github_dev_identity_role_max_session_duration ==
      aws_iam_role.github_dev_identity.max_session_duration
    )
    error_message = "OIDC provider and identity role outputs must expose the declared resources."
  }

  assert {
    condition = (
      output.github_repository_identity == {
        repository          = "philgodoy96/clouddoc-ai-pipeline"
        repository_id       = "987654321"
        repository_owner_id = "12345678"
      } &&
      output.github_identity_workflow_ref ==
      "philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-aws-identity.yml@refs/heads/main" &&
      output.github_trusted_workflow_refs == sort([
        "philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-aws-identity.yml@refs/heads/main",
        "philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-terraform-plan.yml@refs/heads/main",
      ]) &&
      length(output.github_trusted_workflow_refs) == 2
    )
    error_message = "Identity outputs must expose the exact trusted repository, singular identity workflow, and two-value allowlist."
  }
}

run "github_deploy_identity_outputs_contract" {
  command = plan

  assert {
    condition = (
      output.github_deploy_identity_role_name ==
      aws_iam_role.github_dev_deploy_identity.name &&
      output.github_deploy_identity_role_arn ==
      aws_iam_role.github_dev_deploy_identity.arn &&
      output.github_deploy_identity_role_max_session_duration ==
      aws_iam_role.github_dev_deploy_identity.max_session_duration &&
      output.github_deploy_environment == "dev-deploy" &&
      output.github_terraform_deploy_workflow_ref ==
      "philgodoy96/clouddoc-ai-pipeline/.github/workflows/reusable-terraform-deploy.yml@refs/heads/main"
    )
    error_message = "Deployment outputs must expose the exact role, session duration, environment, and workflow contract."
  }

  assert {
    condition = (
      output.github_deploy_trusted_repository_identity == {
        repository          = "philgodoy96/clouddoc-ai-pipeline"
        repository_id       = "987654321"
        repository_owner_id = "12345678"
        environment         = "dev-deploy"
      }
    )
    error_message = "Deployment identity outputs must expose only the approved trusted repository identity fields."
  }
}
