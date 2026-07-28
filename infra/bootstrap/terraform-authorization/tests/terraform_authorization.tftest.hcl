mock_provider "aws" {
  override_during = plan

  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

variables {
  aws_account_id              = "123456789012"
  aws_region                  = "us-east-1"
  environment                 = "dev"
  project_name                = "clouddoc"
  terraform_state_bucket_name = "clouddoc-123456789012-terraform-state"
  terraform_state_key         = "clouddoc/dev/terraform.tfstate"
  github_identity_role_name   = "clouddoc-dev-github-identity"
}

override_resource {
  target          = aws_iam_role.terraform_state
  override_during = plan

  values = {
    arn       = "arn:aws:iam::123456789012:role/clouddoc-dev-terraform-state"
    unique_id = "AROATESTTERRAFORMSTATE"
  }
}

override_resource {
  target          = aws_iam_role.terraform_plan
  override_during = plan

  values = {
    arn       = "arn:aws:iam::123456789012:role/clouddoc-dev-terraform-plan"
    unique_id = "AROATESTTERRAFORMPLAN"
  }
}

run "resource_and_role_contract" {
  command = plan

  assert {
    condition = (
      length([
        for resource in [
          aws_iam_role.terraform_state,
          aws_iam_role.terraform_plan,
          aws_iam_role_policy.terraform_state_access,
          aws_iam_role_policy.terraform_plan_access,
        ] : resource
      ]) == 4
    )
    error_message = "This root must manage exactly two IAM roles and two inline role policies."
  }

  assert {
    condition = (
      aws_iam_role.terraform_state.name == "clouddoc-dev-terraform-state" &&
      aws_iam_role.terraform_plan.name == "clouddoc-dev-terraform-plan" &&
      aws_iam_role.terraform_state.max_session_duration == 3600 &&
      aws_iam_role.terraform_plan.max_session_duration == 3600
    )
    error_message = "The state and plan roles must retain their canonical names and 3600-second max session duration."
  }

  assert {
    condition = (
      local.common_tags == {
        Project     = "clouddoc"
        ManagedBy   = "terraform"
        Component   = "terraform-authorization"
        Scope       = "account"
        Environment = "dev"
      }
    )
    error_message = "The authorization bootstrap must apply the approved common tags."
  }

  assert {
    condition = (
      aws_iam_role_policy.terraform_state_access.name ==
      "clouddoc-dev-terraform-state-access" &&
      aws_iam_role_policy.terraform_plan_access.name ==
      "clouddoc-dev-terraform-plan-access" &&
      aws_iam_role_policy.terraform_state_access.role ==
      aws_iam_role.terraform_state.id &&
      aws_iam_role_policy.terraform_plan_access.role ==
      aws_iam_role.terraform_plan.id
    )
    error_message = "Each inline policy must attach only to its matching authorization role."
  }
}

run "exact_same_account_trust_contract" {
  command = plan

  assert {
    condition = (
      length(data.aws_iam_policy_document.terraform_state_assume_role.statement) == 1 &&
      length(data.aws_iam_policy_document.terraform_plan_assume_role.statement) == 1 &&
      one(data.aws_iam_policy_document.terraform_state_assume_role.statement).sid ==
      "AllowGitHubIdentityAssumeStateRole" &&
      one(data.aws_iam_policy_document.terraform_plan_assume_role.statement).sid ==
      "AllowGitHubIdentityAssumePlanRole"
    )
    error_message = "Each target role must declare exactly one descriptive assume-role statement."
  }

  assert {
    condition = alltrue([
      for statement in [
        one(data.aws_iam_policy_document.terraform_state_assume_role.statement),
        one(data.aws_iam_policy_document.terraform_plan_assume_role.statement),
      ] :
      (
        statement.effect == "Allow" &&
        toset(statement.actions) == toset(["sts:AssumeRole"]) &&
        length(statement.principals) == 1 &&
        one(statement.principals).type == "AWS" &&
        toset(one(statement.principals).identifiers) == toset([
          "arn:aws:iam::123456789012:role/clouddoc-dev-github-identity",
        ]) &&
        length([
          for identifier in one(statement.principals).identifiers : identifier
          if(
            strcontains(identifier, "*") ||
            endswith(identifier, ":root") ||
            strcontains(identifier, "oidc-provider")
          )
        ]) == 0
      )
    ])
    error_message = "Both trust policies must allow only sts:AssumeRole from the exact same-account identity-role ARN."
  }
}

run "exact_state_boundary_contract" {
  command = plan

  assert {
    condition = (
      length(data.aws_iam_policy_document.terraform_state_access.statement) == 3
    )
    error_message = "The state-access policy must contain exactly three statements."
  }

  assert {
    condition = (
      one([
        for statement in data.aws_iam_policy_document.terraform_state_access.statement :
        statement
        if statement.sid == "ListExactStateAndLockPrefixes"
      ]).effect == "Allow" &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_state_access.statement :
          statement
          if statement.sid == "ListExactStateAndLockPrefixes"
        ]).actions
      ) == toset(["s3:ListBucket"]) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_state_access.statement :
          statement
          if statement.sid == "ListExactStateAndLockPrefixes"
        ]).resources
      ) == toset(["arn:aws:s3:::clouddoc-123456789012-terraform-state"]) &&
      length(
        one([
          for statement in data.aws_iam_policy_document.terraform_state_access.statement :
          statement
          if statement.sid == "ListExactStateAndLockPrefixes"
        ]).condition
      ) == 1 &&
      one(
        one([
          for statement in data.aws_iam_policy_document.terraform_state_access.statement :
          statement
          if statement.sid == "ListExactStateAndLockPrefixes"
        ]).condition
      ).test == "StringEquals" &&
      one(
        one([
          for statement in data.aws_iam_policy_document.terraform_state_access.statement :
          statement
          if statement.sid == "ListExactStateAndLockPrefixes"
        ]).condition
      ).variable == "s3:prefix" &&
      toset(
        one(
          one([
            for statement in data.aws_iam_policy_document.terraform_state_access.statement :
            statement
            if statement.sid == "ListExactStateAndLockPrefixes"
          ]).condition
        ).values
        ) == toset([
          "clouddoc/dev/terraform.tfstate",
          "clouddoc/dev/terraform.tfstate.tflock",
      ])
    )
    error_message = "ListBucket must target only the exact state bucket with the exact state and lock prefixes."
  }

  assert {
    condition = (
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_state_access.statement :
          statement
          if statement.sid == "ReadWriteExactStateObject"
        ]).actions
      ) == toset(["s3:GetObject", "s3:PutObject"]) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_state_access.statement :
          statement
          if statement.sid == "ReadWriteExactStateObject"
        ]).resources
        ) == toset([
          "arn:aws:s3:::clouddoc-123456789012-terraform-state/clouddoc/dev/terraform.tfstate",
      ]) &&
      !contains(
        one([
          for statement in data.aws_iam_policy_document.terraform_state_access.statement :
          statement
          if statement.sid == "ReadWriteExactStateObject"
        ]).actions,
        "s3:DeleteObject",
      )
    )
    error_message = "The state object must allow only GetObject and PutObject on the exact state object ARN."
  }

  assert {
    condition = (
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_state_access.statement :
          statement
          if statement.sid == "ManageExactLockObject"
        ]).actions
        ) == toset([
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
      ]) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_state_access.statement :
          statement
          if statement.sid == "ManageExactLockObject"
        ]).resources
        ) == toset([
          "arn:aws:s3:::clouddoc-123456789012-terraform-state/clouddoc/dev/terraform.tfstate.tflock",
      ])
    )
    error_message = "The lock object must allow GetObject, PutObject, and DeleteObject on the exact lock object ARN."
  }

  assert {
    condition = (
      length([
        for action in flatten([
          for statement in data.aws_iam_policy_document.terraform_state_access.statement :
          statement.actions
        ]) : action
        if !startswith(action, "s3:")
      ]) == 0
    )
    error_message = "The state-access policy must not authorize any non-S3 action."
  }
}

run "plan_read_only_boundary_contract" {
  command = plan

  assert {
    condition = (
      length([
        for action in flatten([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement.actions
        ]) : action
        if strcontains(action, "*")
      ]) == 0
    )
    error_message = "The plan-access policy must list every IAM action explicitly without wildcards."
  }

  assert {
    condition = (
      length([
        for action in flatten([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement.actions
        ]) : action
        if can(regex(
          ":(Create|Update|Delete|Put|Set|Tag|Untag|Invoke|Send|Start|Stop|PassRole|Attach|Detach|Add|Remove|Publish|Purge|Redrive)",
          action,
        ))
      ]) == 0 &&
      !contains(
        flatten([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement.actions
        ]),
        "iam:PassRole",
      ) &&
      length([
        for action in flatten([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement.actions
        ]) : action
        if(
          startswith(action, "lambda:Invoke") ||
          startswith(action, "sqs:Receive") ||
          startswith(action, "sqs:Send") ||
          startswith(action, "sqs:DeleteMessage") ||
          startswith(action, "sqs:ChangeMessage") ||
          startswith(action, "sqs:Purge") ||
          startswith(action, "dynamodb:GetItem") ||
          startswith(action, "dynamodb:Query") ||
          startswith(action, "dynamodb:Scan") ||
          startswith(action, "dynamodb:BatchGet") ||
          action == "s3:GetObject" ||
          action == "s3:PutObject" ||
          action == "s3:DeleteObject"
        )
      ]) == 0
    )
    error_message = "The plan-access policy must exclude mutation, PassRole, invocation, and data-plane actions."
  }

  assert {
    condition = (
      length([
        for resource in flatten([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement.resources
        ]) : resource
        if(
          strcontains(resource, "terraform.tfstate") ||
          strcontains(resource, "clouddoc-123456789012-terraform-state") ||
          endswith(resource, ".tflock")
        )
      ]) == 0
    )
    error_message = "The plan-access policy must not reference Terraform state or lock objects."
  }

  assert {
    condition = (
      length([
        for service in [
          "apigateway:",
          "cloudwatch:",
          "logs:",
          "dynamodb:",
          "iam:",
          "lambda:",
          "s3:",
          "sqs:",
          "sts:",
        ] : service
        if length([
          for action in flatten([
            for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
            statement.actions
          ]) : action
          if startswith(action, service)
        ]) > 0
      ]) == 9
    )
    error_message = "The plan-access policy must cover every approved application service family."
  }

  assert {
    condition = alltrue([
      for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
      (
        length(statement.actions) > 0 &&
        length(statement.resources) > 0 &&
        alltrue([
          for action in statement.actions :
          can(regex("^[a-z0-9]+:[A-Za-z0-9]+$", action))
        ])
      )
    ])
    error_message = "Every plan-access statement must contain only explicit service:Action names and resources."
  }
}

run "outputs_contract" {
  command = plan

  assert {
    condition = (
      output.terraform_state_role_name == "clouddoc-dev-terraform-state" &&
      output.terraform_plan_role_name == "clouddoc-dev-terraform-plan" &&
      output.terraform_state_role_arn ==
      "arn:aws:iam::123456789012:role/clouddoc-dev-terraform-state" &&
      output.terraform_plan_role_arn ==
      "arn:aws:iam::123456789012:role/clouddoc-dev-terraform-plan" &&
      output.terraform_state_role_max_session_duration == 3600 &&
      output.terraform_plan_role_max_session_duration == 3600
    )
    error_message = "Role outputs must expose the exact state and plan role identifiers and session duration."
  }

  assert {
    condition = (
      output.github_identity_role_arn ==
      "arn:aws:iam::123456789012:role/clouddoc-dev-github-identity" &&
      output.terraform_state_bucket_name ==
      "clouddoc-123456789012-terraform-state" &&
      output.terraform_state_key == "clouddoc/dev/terraform.tfstate" &&
      output.terraform_lock_key == "clouddoc/dev/terraform.tfstate.tflock" &&
      output.terraform_state_object_arn ==
      "arn:aws:s3:::clouddoc-123456789012-terraform-state/clouddoc/dev/terraform.tfstate" &&
      output.terraform_lock_object_arn ==
      "arn:aws:s3:::clouddoc-123456789012-terraform-state/clouddoc/dev/terraform.tfstate.tflock"
    )
    error_message = "Outputs must expose the exact identity principal and derived state and lock paths."
  }
}
