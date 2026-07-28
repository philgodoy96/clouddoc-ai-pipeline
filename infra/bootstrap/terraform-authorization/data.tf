data "aws_partition" "current" {}

data "aws_iam_policy_document" "terraform_state_assume_role" {
  statement {
    sid    = "AllowGitHubIdentityAssumeStateRole"
    effect = "Allow"

    actions = [
      "sts:AssumeRole",
    ]

    principals {
      type = "AWS"

      identifiers = local.terraform_state_trusted_identity_role_arns
    }
  }
}

data "aws_iam_policy_document" "terraform_plan_assume_role" {
  statement {
    sid    = "AllowGitHubIdentityAssumePlanRole"
    effect = "Allow"

    actions = [
      "sts:AssumeRole",
    ]

    principals {
      type = "AWS"

      identifiers = [
        local.github_identity_role_arn,
      ]
    }
  }
}

data "aws_iam_policy_document" "terraform_apply_assume_role" {
  statement {
    sid    = "AllowGitHubDeployIdentityAssumeApplyRole"
    effect = "Allow"

    actions = [
      "sts:AssumeRole",
    ]

    principals {
      type = "AWS"

      identifiers = [
        local.github_deploy_identity_role_arn,
      ]
    }
  }
}

data "aws_iam_policy_document" "terraform_state_access" {
  statement {
    sid    = "ListExactStateAndLockPrefixes"
    effect = "Allow"

    actions = [
      "s3:ListBucket",
    ]

    resources = [
      local.terraform_state_bucket_arn,
    ]

    condition {
      test     = "StringEquals"
      variable = "s3:prefix"

      values = [
        var.terraform_state_key,
        local.terraform_lock_key,
      ]
    }
  }

  statement {
    sid    = "ReadWriteExactStateObject"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]

    resources = [
      local.terraform_state_object_arn,
    ]
  }

  statement {
    sid    = "ManageExactLockObject"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]

    resources = [
      local.terraform_lock_object_arn,
    ]
  }
}

data "aws_iam_policy_document" "terraform_plan_access" {
  # API Gateway HTTP API IDs are assigned by AWS before state refresh can
  # resolve a narrower management ARN.
  statement {
    sid    = "ReadApiGatewayV2ControlPlane"
    effect = "Allow"

    actions = [
      "apigateway:GET",
    ]

    resources = [
      "*",
    ]
  }

  statement {
    sid    = "ReadCloudWatchAlarms"
    effect = "Allow"

    actions = [
      "cloudwatch:DescribeAlarms",
      "cloudwatch:ListTagsForResource",
    ]

    resources = [
      local.application_alarm_arn_prefix,
    ]
  }

  statement {
    sid    = "ReadCloudWatchDashboard"
    effect = "Allow"

    actions = [
      "cloudwatch:GetDashboard",
      "cloudwatch:ListTagsForResource",
    ]

    resources = [
      local.operations_dashboard_arn,
    ]
  }

  # DescribeLogGroups does not support resource-level IAM permissions.
  statement {
    sid    = "DescribeCloudWatchLogGroups"
    effect = "Allow"

    actions = [
      "logs:DescribeLogGroups",
    ]

    resources = [
      "*",
    ]
  }

  statement {
    sid    = "ReadCloudWatchLogGroupTags"
    effect = "Allow"

    actions = [
      "logs:ListTagsForResource",
    ]

    resources = local.application_log_group_arns
  }

  statement {
    sid    = "ReadDynamoDBTableMetadata"
    effect = "Allow"

    actions = [
      "dynamodb:DescribeContinuousBackups",
      "dynamodb:DescribeContributorInsights",
      "dynamodb:DescribeTable",
      "dynamodb:DescribeTimeToLive",
      "dynamodb:ListTagsOfResource",
    ]

    resources = [
      local.document_jobs_table_arn,
    ]
  }

  statement {
    sid    = "ReadApplicationIamRoles"
    effect = "Allow"

    actions = [
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
      "iam:ListRolePolicies",
      "iam:ListRoleTags",
    ]

    resources = local.application_iam_role_arns
  }

  statement {
    sid    = "ReadLambdaFunctionMetadata"
    effect = "Allow"

    actions = [
      "lambda:GetFunction",
      "lambda:GetFunctionCodeSigningConfig",
      "lambda:GetFunctionConcurrency",
      "lambda:GetFunctionEventInvokeConfig",
      "lambda:GetPolicy",
      "lambda:GetRuntimeManagementConfig",
      "lambda:ListFunctionEventInvokeConfigs",
      "lambda:ListTags",
      "lambda:ListVersionsByFunction",
    ]

    resources = local.application_lambda_function_arns
  }

  # GetEventSourceMapping does not support resource-level restriction.
  statement {
    sid    = "ReadLambdaEventSourceMappings"
    effect = "Allow"

    actions = [
      "lambda:GetEventSourceMapping",
    ]

    resources = [
      "*",
    ]
  }

  statement {
    sid    = "ReadDocumentsBucketConfiguration"
    effect = "Allow"

    actions = [
      "s3:GetAccelerateConfiguration",
      "s3:GetBucketAcl",
      "s3:GetBucketCORS",
      "s3:GetLifecycleConfiguration",
      "s3:GetBucketLocation",
      "s3:GetBucketLogging",
      "s3:GetBucketNotification",
      "s3:GetBucketObjectLockConfiguration",
      "s3:GetBucketOwnershipControls",
      "s3:GetBucketPolicy",
      "s3:GetBucketPolicyStatus",
      "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketRequestPayment",
      "s3:GetBucketTagging",
      "s3:GetBucketVersioning",
      "s3:GetBucketWebsite",
      "s3:GetEncryptionConfiguration",
      "s3:GetReplicationConfiguration",
      "s3:ListBucket",
    ]

    resources = [
      local.documents_bucket_arn,
    ]
  }

  statement {
    sid    = "ReadApplicationSqsQueueMetadata"
    effect = "Allow"

    actions = [
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
      "sqs:ListQueueTags",
    ]

    resources = local.application_sqs_queue_arns
  }

  # GetCallerIdentity is account-scoped and does not accept a resource ARN.
  statement {
    sid    = "ReadCallerIdentity"
    effect = "Allow"

    actions = [
      "sts:GetCallerIdentity",
    ]

    resources = [
      "*",
    ]
  }
}
