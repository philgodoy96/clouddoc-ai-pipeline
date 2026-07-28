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
  aws_account_id                   = "123456789012"
  aws_region                       = "us-east-1"
  environment                      = "dev"
  project_name                     = "clouddoc"
  terraform_state_bucket_name      = "clouddoc-123456789012-terraform-state"
  terraform_state_key              = "clouddoc/dev/terraform.tfstate"
  github_identity_role_name        = "clouddoc-dev-github-identity"
  github_deploy_identity_role_name = "clouddoc-dev-github-deploy-identity"
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

override_resource {
  target          = aws_iam_role.terraform_apply
  override_during = plan

  values = {
    arn       = "arn:aws:iam::123456789012:role/clouddoc-dev-terraform-apply"
    unique_id = "AROATESTTERRAFORMAPPLY"
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
          aws_iam_role.terraform_apply,
          aws_iam_role_policy.terraform_state_access,
          aws_iam_role_policy.terraform_plan_access,
          aws_iam_role_policy.terraform_apply_access,
        ] : resource
      ]) == 6
    )
    error_message = "This root must manage exactly three IAM roles and three inline role policies."
  }

  assert {
    condition = (
      aws_iam_role.terraform_state.name == "clouddoc-dev-terraform-state" &&
      aws_iam_role.terraform_plan.name == "clouddoc-dev-terraform-plan" &&
      aws_iam_role.terraform_apply.name == "clouddoc-dev-terraform-apply" &&
      aws_iam_role.terraform_state.max_session_duration == 3600 &&
      aws_iam_role.terraform_plan.max_session_duration == 3600 &&
      aws_iam_role.terraform_apply.max_session_duration == 3600
    )
    error_message = "The authorization roles must retain their canonical names and 3600-second max session duration."
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
      aws_iam_role_policy.terraform_apply_access.name ==
      "clouddoc-dev-terraform-apply-access" &&
      aws_iam_role_policy.terraform_state_access.role ==
      aws_iam_role.terraform_state.id &&
      aws_iam_role_policy.terraform_plan_access.role ==
      aws_iam_role.terraform_plan.id &&
      aws_iam_role_policy.terraform_apply_access.role ==
      aws_iam_role.terraform_apply.name
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
      length(data.aws_iam_policy_document.terraform_apply_assume_role.statement) == 1 &&
      one(data.aws_iam_policy_document.terraform_state_assume_role.statement).sid ==
      "AllowGitHubIdentityAssumeStateRole" &&
      one(data.aws_iam_policy_document.terraform_plan_assume_role.statement).sid ==
      "AllowGitHubIdentityAssumePlanRole" &&
      one(data.aws_iam_policy_document.terraform_apply_assume_role.statement).sid ==
      "AllowGitHubDeployIdentityAssumeApplyRole"
    )
    error_message = "Each target role must declare exactly one descriptive assume-role statement."
  }

  assert {
    condition = (
      one(data.aws_iam_policy_document.terraform_state_assume_role.statement).effect == "Allow" &&
      toset(one(data.aws_iam_policy_document.terraform_state_assume_role.statement).actions) == toset(["sts:AssumeRole"]) &&
      length(one(data.aws_iam_policy_document.terraform_state_assume_role.statement).principals) == 1 &&
      one(one(data.aws_iam_policy_document.terraform_state_assume_role.statement).principals).type == "AWS" &&
      toset(one(one(data.aws_iam_policy_document.terraform_state_assume_role.statement).principals).identifiers) == toset([
        "arn:aws:iam::123456789012:role/clouddoc-dev-github-deploy-identity",
        "arn:aws:iam::123456789012:role/clouddoc-dev-github-identity",
      ]) &&
      one(data.aws_iam_policy_document.terraform_plan_assume_role.statement).effect == "Allow" &&
      toset(one(data.aws_iam_policy_document.terraform_plan_assume_role.statement).actions) == toset(["sts:AssumeRole"]) &&
      length(one(data.aws_iam_policy_document.terraform_plan_assume_role.statement).principals) == 1 &&
      one(one(data.aws_iam_policy_document.terraform_plan_assume_role.statement).principals).type == "AWS" &&
      toset(one(one(data.aws_iam_policy_document.terraform_plan_assume_role.statement).principals).identifiers) == toset([
        "arn:aws:iam::123456789012:role/clouddoc-dev-github-identity",
      ]) &&
      one(data.aws_iam_policy_document.terraform_apply_assume_role.statement).effect == "Allow" &&
      toset(one(data.aws_iam_policy_document.terraform_apply_assume_role.statement).actions) == toset(["sts:AssumeRole"]) &&
      length(one(data.aws_iam_policy_document.terraform_apply_assume_role.statement).principals) == 1 &&
      one(one(data.aws_iam_policy_document.terraform_apply_assume_role.statement).principals).type == "AWS" &&
      toset(one(one(data.aws_iam_policy_document.terraform_apply_assume_role.statement).principals).identifiers) == toset([
        "arn:aws:iam::123456789012:role/clouddoc-dev-github-deploy-identity",
      ])
    )
    error_message = "State, plan, and apply trust policies must use the reviewed same-account identity-role principals only."
  }

  assert {
    condition = alltrue([
      for identifier in flatten([
        one(one(data.aws_iam_policy_document.terraform_state_assume_role.statement).principals).identifiers,
        one(one(data.aws_iam_policy_document.terraform_plan_assume_role.statement).principals).identifiers,
        one(one(data.aws_iam_policy_document.terraform_apply_assume_role.statement).principals).identifiers,
      ]) :
      !strcontains(identifier, "*") &&
      !endswith(identifier, ":root") &&
      !strcontains(identifier, "oidc-provider")
    ])
    error_message = "Authorization trusts must exclude wildcard, account-root, and direct OIDC principals."
  }

  assert {
    condition = (
      aws_iam_role.terraform_apply.max_session_duration == 3600
    )
    error_message = "The apply role max session duration must remain 3600 seconds."
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

  assert {
    condition = (
      contains(
        one([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement
          if statement.sid == "ReadDocumentsBucketConfiguration"
        ]).actions,
        "s3:GetLifecycleConfiguration",
      ) &&
      !contains(
        one([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement
          if statement.sid == "ReadDocumentsBucketConfiguration"
        ]).actions,
        "s3:GetBucketLifecycleConfiguration",
      ) &&
      !contains(
        flatten([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement.actions
        ]),
        "s3:GetBucketLifecycleConfiguration",
      ) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement
          if statement.sid == "ReadDocumentsBucketConfiguration"
        ]).resources
      ) == toset([local.documents_bucket_arn]) &&
      !contains(
        one([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement
          if statement.sid == "ReadDocumentsBucketConfiguration"
        ]).resources,
        "*",
      ) &&
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
    error_message = "Plan ReadDocumentsBucketConfiguration must use s3:GetLifecycleConfiguration only on the documents bucket, remain read-only, and stay state-free."
  }

  assert {
    condition = (
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement
          if statement.sid == "ReadLambdaEventSourceMappings"
        ]).actions
      ) == toset(["lambda:GetEventSourceMapping"]) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement
          if statement.sid == "ReadLambdaEventSourceMappings"
        ]).resources
      ) == toset(["*"]) &&
      length(
        one([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement
          if statement.sid == "ReadLambdaEventSourceMappings"
        ]).condition
      ) == 0 &&
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
      ]) == 0 &&
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
    error_message = "Plan ReadLambdaEventSourceMappings must use GetEventSourceMapping on * only, remaining mutation-free, state-free, invocation-free, and data-plane-free."
  }
}

run "apply_boundary_contract" {
  command = plan

  assert {
    condition = (
      toset([
        for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
        statement.sid
        ]) == toset([
        "ReadCallerIdentity",
        "ManageApiGatewayV2ControlPlane",
        "DescribeCloudWatchAlarmMetrics",
        "ManageCloudWatchAlarms",
        "ListCloudWatchDashboards",
        "ManageCloudWatchDashboard",
        "DescribeCloudWatchLogGroups",
        "ManageCloudWatchLogGroups",
        "ManageCloudWatchLogGroupTags",
        "ManageDynamoDBTableControlPlane",
        "ManageLambdaExecutionRoles",
        "ManageLambdaExecutionRoleInlinePolicies",
        "PassOnlyLambdaExecutionRolesToLambdaService",
        "ManageLambdaFunctions",
        "ManageLambdaPermissions",
        "ListLambdaEventSourceMappings",
        "ReadLambdaEventSourceMapping",
        "ManageLambdaEventSourceMappings",
        "ReadDocumentsBucketConfiguration",
        "ManageDocumentsBucketControlPlane",
        "ManageApplicationSqsQueues",
      ])
    )
    error_message = "The apply policy must keep the reviewed service-specific statement set."
  }

  assert {
    condition = (
      length([
        for action in flatten([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement.actions
        ]) : action
        if strcontains(action, "*")
      ]) == 0
    )
    error_message = "The apply policy must enumerate explicit actions only."
  }

  assert {
    condition = (
      length([
        for resource in flatten([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement.resources
        ]) : resource
        if(
          strcontains(resource, "clouddoc-123456789012-terraform-state") ||
          strcontains(resource, "terraform.tfstate") ||
          strcontains(resource, ".tflock")
        )
      ]) == 0
    )
    error_message = "The apply policy must not reference the Terraform state bucket, state object, or lock object."
  }

  assert {
    condition = (
      length([
        for action in flatten([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement.actions
        ]) : action
        if contains([
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "lambda:InvokeFunction",
          "lambda:InvokeAsync",
          "execute-api:Invoke",
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:ChangeMessageVisibility",
          "sqs:PurgeQueue",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "bedrock:InvokeModel",
          "kms:Decrypt",
          "kms:Encrypt",
          "secretsmanager:GetSecretValue",
          "iam:CreateAccessKey",
          "iam:AttachRolePolicy",
          "iam:CreatePolicy",
        ], action)
      ]) == 0
    )
    error_message = "The apply policy must exclude application data-plane, invocation, static credential, and prohibited service-family actions."
  }

  assert {
    condition = (
      length([
        for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
        statement
        if contains(statement.actions, "iam:PassRole")
      ]) == 1 &&
      toset(one([
        for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
        statement
        if contains(statement.actions, "iam:PassRole")
        ]).resources) == toset([
        "arn:aws:iam::123456789012:role/clouddoc-dev-create-job-role",
        "arn:aws:iam::123456789012:role/clouddoc-dev-get-job-role",
        "arn:aws:iam::123456789012:role/clouddoc-dev-process-document-role",
        "arn:aws:iam::123456789012:role/clouddoc-dev-reconcile-dead-letter-role",
      ]) &&
      one(one([
        for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
        statement
        if contains(statement.actions, "iam:PassRole")
      ]).condition).test == "StringEquals" &&
      one(one([
        for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
        statement
        if contains(statement.actions, "iam:PassRole")
      ]).condition).variable == "iam:PassedToService" &&
      toset(one(one([
        for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
        statement
        if contains(statement.actions, "iam:PassRole")
      ]).condition).values) == toset(["lambda.amazonaws.com"])
    )
    error_message = "PassRole must appear exactly once, target only the four Lambda execution roles, and restrict passing to lambda.amazonaws.com."
  }

  assert {
    condition = (
      toset([
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
            for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
            statement.actions
          ]) : action
          if startswith(action, service)
        ]) > 0
        ]) == toset([
        "apigateway:",
        "cloudwatch:",
        "logs:",
        "dynamodb:",
        "iam:",
        "lambda:",
        "s3:",
        "sqs:",
        "sts:",
      ])
    )
    error_message = "The apply policy must remain within the reviewed service families only."
  }

  assert {
    condition = (
      contains(
        flatten([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement.actions
        ]),
        "s3:GetLifecycleConfiguration",
      ) &&
      !contains(
        flatten([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement.actions
        ]),
        "s3:GetBucketLifecycleConfiguration",
      ) &&
      contains(
        flatten([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement.actions
        ]),
        "s3:PutLifecycleConfiguration",
      )
    )
    error_message = "Apply S3 lifecycle authorization must use GetLifecycleConfiguration and PutLifecycleConfiguration only."
  }

  assert {
    condition = (
      length([
        for action in flatten([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement.actions
        ]) : action
        if contains([
          "s3:DeleteBucketEncryption",
          "s3:DeleteBucketOwnershipControls",
          "s3:DeleteBucketTagging",
          "s3:DeleteBucketPublicAccessBlock",
        ], action)
      ]) == 0
    )
    error_message = "Apply S3 control-plane authorization must exclude the invalid Delete* action names."
  }

  assert {
    condition = (
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroups"
        ]).actions
        ) == toset([
          "logs:CreateLogGroup",
          "logs:DeleteLogGroup",
          "logs:DeleteRetentionPolicy",
          "logs:PutRetentionPolicy",
      ]) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroups"
        ]).resources
      ) == toset(local.application_log_group_management_arns) &&
      length(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroups"
        ]).resources
      ) == 5 &&
      alltrue([
        for resource in one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroups"
        ]).resources :
        endswith(resource, ":*") && resource != "*"
      ]) &&
      !contains(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroups"
        ]).resources,
        "*",
      ) &&
      length(setintersection(
        toset(
          one([
            for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
            statement
            if statement.sid == "ManageCloudWatchLogGroups"
          ]).actions
        ),
        toset([
          "logs:ListTagsForResource",
          "logs:TagResource",
          "logs:UntagResource",
        ])
      )) == 0
    )
    error_message = "ManageCloudWatchLogGroups must use exactly the four management actions on the five :* ARNs, without tagging actions or unrestricted *."
  }

  assert {
    condition = (
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroupTags"
        ]).actions
        ) == toset([
          "logs:ListTagsForResource",
          "logs:TagResource",
          "logs:UntagResource",
      ]) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroupTags"
        ]).resources
      ) == toset(local.application_log_group_arns) &&
      length(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroupTags"
        ]).resources
      ) == 5 &&
      alltrue([
        for resource in one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroupTags"
        ]).resources :
        !endswith(resource, ":*") && resource != "*"
      ]) &&
      !contains(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroupTags"
        ]).resources,
        "*",
      )
    )
    error_message = "ManageCloudWatchLogGroupTags must use exactly the three tagging actions on the five bare ARNs, without management :* ARNs or unrestricted *."
  }

  assert {
    condition = (
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageApiGatewayV2ControlPlane"
        ]).actions
        ) == toset([
          "apigateway:DELETE",
          "apigateway:GET",
          "apigateway:PATCH",
          "apigateway:POST",
      ]) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageApiGatewayV2ControlPlane"
        ]).resources
        ) == toset([
          "arn:aws:apigateway:us-east-1::/apis",
          "arn:aws:apigateway:us-east-1::/apis/*",
          "arn:aws:apigateway:us-east-1::/apis/*/integrations",
          "arn:aws:apigateway:us-east-1::/apis/*/integrations/*",
          "arn:aws:apigateway:us-east-1::/apis/*/routes",
          "arn:aws:apigateway:us-east-1::/apis/*/routes/*",
          "arn:aws:apigateway:us-east-1::/apis/*/stages",
          "arn:aws:apigateway:us-east-1::/apis/*/stages/*",
          "arn:aws:apigateway:us-east-1::/tags/arn%3Aaws%3Aapigateway%3Aus-east-1%3A%3A%2Fv2%2Fapis%2F*",
          "arn:aws:apigateway:us-east-1::/tags/arn%3Aaws%3Aapigateway%3Aus-east-1%3A%3A%2Fv2%2Fapis%2F*%2Fstages%2F*",
      ]) &&
      local.application_apigateway_stage_tag_resource ==
      "arn:aws:apigateway:us-east-1::/tags/arn%3Aaws%3Aapigateway%3Aus-east-1%3A%3A%2Fv2%2Fapis%2F*%2Fstages%2F*" &&
      contains(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageApiGatewayV2ControlPlane"
        ]).resources,
        local.application_apigateway_api_tag_resource,
      ) &&
      contains(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageApiGatewayV2ControlPlane"
        ]).resources,
        local.application_apigateway_stage_tag_resource,
      ) &&
      !contains(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageApiGatewayV2ControlPlane"
        ]).resources,
        "*",
      ) &&
      !contains(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageApiGatewayV2ControlPlane"
        ]).resources,
        "arn:aws:apigateway:us-east-1::/tags/*",
      ) &&
      !contains(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageApiGatewayV2ControlPlane"
        ]).actions,
        "execute-api:Invoke",
      )
    )
    error_message = "ManageApiGatewayV2ControlPlane must keep the four HTTP actions, normal API scopes, and both encoded API/Stage tag resources, without unrestricted * or generic /tags/*."
  }

  assert {
    condition = (
      length(local.application_lambda_event_source_mapping_function_arns) == 2 &&
      toset(local.application_lambda_event_source_mapping_function_arns) == toset([
        "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-process-document",
        "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-reconcile-dead-letter",
      ]) &&
      !contains(
        local.application_lambda_event_source_mapping_function_arns,
        "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-create-job",
      ) &&
      !contains(
        local.application_lambda_event_source_mapping_function_arns,
        "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-get-job",
      ) &&
      alltrue([
        for arn in local.application_lambda_event_source_mapping_function_arns :
        !strcontains(arn, "*") &&
        !strcontains(arn, "event-source-mapping") &&
        !strcontains(arn, ":sqs:")
      ])
    )
    error_message = "Event-source mapping FunctionArn boundary must be exactly the processor and dead-letter-reconciler function ARNs."
  }

  assert {
    condition = (
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ListLambdaEventSourceMappings"
        ]).actions
      ) == toset(["lambda:ListEventSourceMappings"]) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ListLambdaEventSourceMappings"
        ]).resources
      ) == toset(["*"]) &&
      length(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ListLambdaEventSourceMappings"
        ]).condition
      ) == 0
    )
    error_message = "ListLambdaEventSourceMappings must use only ListEventSourceMappings on * with no conditions."
  }

  assert {
    condition = (
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ReadLambdaEventSourceMapping"
        ]).actions
      ) == toset(["lambda:GetEventSourceMapping"]) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ReadLambdaEventSourceMapping"
        ]).resources
      ) == toset(["*"]) &&
      length(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ReadLambdaEventSourceMapping"
        ]).condition
      ) == 0
    )
    error_message = "ReadLambdaEventSourceMapping must use only GetEventSourceMapping on * with no conditions."
  }

  assert {
    condition = (
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageLambdaEventSourceMappings"
        ]).actions
        ) == toset([
          "lambda:CreateEventSourceMapping",
          "lambda:DeleteEventSourceMapping",
          "lambda:UpdateEventSourceMapping",
      ]) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageLambdaEventSourceMappings"
        ]).resources
      ) == toset(["*"]) &&
      length(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageLambdaEventSourceMappings"
        ]).condition
      ) == 1 &&
      one(one([
        for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
        statement
        if statement.sid == "ManageLambdaEventSourceMappings"
      ]).condition).test == "ArnLike" &&
      one(one([
        for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
        statement
        if statement.sid == "ManageLambdaEventSourceMappings"
      ]).condition).variable == "lambda:FunctionArn" &&
      toset(one(one([
        for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
        statement
        if statement.sid == "ManageLambdaEventSourceMappings"
      ]).condition).values) == toset(local.application_lambda_event_source_mapping_function_arns) &&
      toset(one(one([
        for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
        statement
        if statement.sid == "ManageLambdaEventSourceMappings"
        ]).condition).values) == toset([
        "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-process-document",
        "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-reconcile-dead-letter",
      ]) &&
      !contains(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageLambdaEventSourceMappings"
        ]).actions,
        "lambda:GetEventSourceMapping",
      ) &&
      !contains(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageLambdaEventSourceMappings"
        ]).actions,
        "lambda:ListEventSourceMappings",
      ) &&
      alltrue([
        for value in one(one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageLambdaEventSourceMappings"
        ]).condition).values :
        !strcontains(value, "*")
      ]) &&
      !contains(
        one(one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageLambdaEventSourceMappings"
        ]).condition).values,
        "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-create-job",
      ) &&
      !contains(
        one(one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageLambdaEventSourceMappings"
        ]).condition).values,
        "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-get-job",
      )
    )
    error_message = "ManageLambdaEventSourceMappings must mutate only via Create/Delete/Update on * with ArnLike lambda:FunctionArn limited to the two consumer functions."
  }
}

run "cloudwatch_log_group_arn_contract" {
  command = plan

  assert {
    condition = (
      length(local.application_log_group_arns) == 5 &&
      alltrue([
        for resource in local.application_log_group_arns :
        !endswith(resource, ":*") && resource != "*"
      ]) &&
      length([
        for resource in local.application_log_group_arns :
        resource if strcontains(resource, ":log-group:/aws/lambda/")
      ]) == 4 &&
      length([
        for resource in local.application_log_group_arns :
        resource if strcontains(resource, ":log-group:/aws/apigateway/")
      ]) == 1 &&
      length(local.application_log_group_management_arns) == 5 &&
      alltrue([
        for resource in local.application_log_group_management_arns :
        endswith(resource, ":*") && resource != "*"
      ]) &&
      toset([
        for resource in local.application_log_group_management_arns :
        trimsuffix(resource, ":*")
      ]) == toset(local.application_log_group_arns) &&
      toset(local.application_log_group_arns) != toset(local.application_log_group_management_arns)
    )
    error_message = "Tagging and management log-group ARN locals must be distinct five-entry sets (4 Lambda + 1 API Gateway) linked by a trailing :*."
  }

  assert {
    condition = (
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement
          if statement.sid == "ReadCloudWatchLogGroupTags"
        ]).actions
      ) == toset(["logs:ListTagsForResource"]) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement
          if statement.sid == "ReadCloudWatchLogGroupTags"
        ]).resources
      ) == toset(local.application_log_group_arns) &&
      length(
        one([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement
          if statement.sid == "ReadCloudWatchLogGroupTags"
        ]).resources
      ) == 5 &&
      alltrue([
        for resource in one([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement
          if statement.sid == "ReadCloudWatchLogGroupTags"
        ]).resources :
        !endswith(resource, ":*") && resource != "*"
      ]) &&
      !contains(
        one([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement
          if statement.sid == "ReadCloudWatchLogGroupTags"
        ]).resources,
        "*",
      )
    )
    error_message = "ReadCloudWatchLogGroupTags must use only logs:ListTagsForResource on the five bare tagging ARNs."
  }

  assert {
    condition = (
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroups"
        ]).actions
        ) == toset([
          "logs:CreateLogGroup",
          "logs:DeleteLogGroup",
          "logs:DeleteRetentionPolicy",
          "logs:PutRetentionPolicy",
      ]) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroups"
        ]).resources
      ) == toset(local.application_log_group_management_arns) &&
      length(setintersection(
        toset(
          one([
            for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
            statement
            if statement.sid == "ManageCloudWatchLogGroups"
          ]).actions
        ),
        toset([
          "logs:ListTagsForResource",
          "logs:TagResource",
          "logs:UntagResource",
        ])
      )) == 0 &&
      !contains(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroups"
        ]).resources,
        "*",
      )
    )
    error_message = "ManageCloudWatchLogGroups must keep exactly the four management actions on management ARNs, without tagging actions."
  }

  assert {
    condition = (
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroupTags"
        ]).actions
        ) == toset([
          "logs:ListTagsForResource",
          "logs:TagResource",
          "logs:UntagResource",
      ]) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroupTags"
        ]).resources
      ) == toset(local.application_log_group_arns) &&
      alltrue([
        for resource in one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroupTags"
        ]).resources :
        !endswith(resource, ":*") && resource != "*"
      ]) &&
      !contains(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroupTags"
        ]).resources,
        "*",
      )
    )
    error_message = "ManageCloudWatchLogGroupTags must use exactly the three tagging actions on bare ARNs only."
  }

  assert {
    condition = (
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroups"
        ]).resources
      ) == toset(local.application_log_group_management_arns) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement
          if statement.sid == "ReadCloudWatchLogGroupTags"
        ]).resources
        ) != toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroups"
        ]).resources
      ) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroupTags"
        ]).resources
      ) == toset(local.application_log_group_arns) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroupTags"
        ]).resources
        ) == toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement
          if statement.sid == "ReadCloudWatchLogGroupTags"
        ]).resources
      ) &&
      toset([
        for resource in one([
          for statement in data.aws_iam_policy_document.terraform_apply_access.statement :
          statement
          if statement.sid == "ManageCloudWatchLogGroups"
        ]).resources :
        trimsuffix(resource, ":*")
        ]) == toset(
        one([
          for statement in data.aws_iam_policy_document.terraform_plan_access.statement :
          statement
          if statement.sid == "ReadCloudWatchLogGroupTags"
        ]).resources
      )
    )
    error_message = "Plan/Apply tagging must share bare ARNs; Apply management must remain the distinct :*-linked set."
  }
}

run "outputs_contract" {
  command = plan

  assert {
    condition = (
      output.terraform_state_role_name == "clouddoc-dev-terraform-state" &&
      output.terraform_plan_role_name == "clouddoc-dev-terraform-plan" &&
      output.terraform_apply_role_name == "clouddoc-dev-terraform-apply" &&
      output.terraform_state_role_arn ==
      "arn:aws:iam::123456789012:role/clouddoc-dev-terraform-state" &&
      output.terraform_plan_role_arn ==
      "arn:aws:iam::123456789012:role/clouddoc-dev-terraform-plan" &&
      output.terraform_apply_role_arn ==
      "arn:aws:iam::123456789012:role/clouddoc-dev-terraform-apply" &&
      output.terraform_state_role_max_session_duration == 3600 &&
      output.terraform_plan_role_max_session_duration == 3600 &&
      output.terraform_apply_role_max_session_duration == 3600
    )
    error_message = "Role outputs must expose the exact state, plan, and apply role identifiers and session duration."
  }

  assert {
    condition = (
      output.github_identity_role_arn ==
      "arn:aws:iam::123456789012:role/clouddoc-dev-github-identity" &&
      output.github_deploy_identity_role_arn ==
      "arn:aws:iam::123456789012:role/clouddoc-dev-github-deploy-identity" &&
      toset(output.terraform_state_trusted_identity_role_arns) == toset([
        "arn:aws:iam::123456789012:role/clouddoc-dev-github-identity",
        "arn:aws:iam::123456789012:role/clouddoc-dev-github-deploy-identity",
      ]) &&
      output.terraform_apply_trusted_identity_role_arn ==
      "arn:aws:iam::123456789012:role/clouddoc-dev-github-deploy-identity" &&
      toset(output.lambda_execution_role_arns) == toset([
        "arn:aws:iam::123456789012:role/clouddoc-dev-create-job-role",
        "arn:aws:iam::123456789012:role/clouddoc-dev-get-job-role",
        "arn:aws:iam::123456789012:role/clouddoc-dev-process-document-role",
        "arn:aws:iam::123456789012:role/clouddoc-dev-reconcile-dead-letter-role",
      ]) &&
      output.terraform_state_bucket_name ==
      "clouddoc-123456789012-terraform-state" &&
      output.terraform_state_key == "clouddoc/dev/terraform.tfstate" &&
      output.terraform_lock_key == "clouddoc/dev/terraform.tfstate.tflock" &&
      output.terraform_state_object_arn ==
      "arn:aws:s3:::clouddoc-123456789012-terraform-state/clouddoc/dev/terraform.tfstate" &&
      output.terraform_lock_object_arn ==
      "arn:aws:s3:::clouddoc-123456789012-terraform-state/clouddoc/dev/terraform.tfstate.tflock"
    )
    error_message = "Outputs must expose the exact trust principals, PassRole role ARNs, and derived state and lock paths."
  }
}
