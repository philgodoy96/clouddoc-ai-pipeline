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

data "aws_iam_policy_document" "terraform_apply_access" {
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

  statement {
    sid    = "ManageApiGatewayV2ControlPlane"
    effect = "Allow"

    actions = [
      "apigateway:DELETE",
      "apigateway:GET",
      "apigateway:PATCH",
      "apigateway:POST",
    ]

    resources = [
      local.application_apigateway_apis_resource,
      local.application_apigateway_api_resource_prefix,
      local.application_apigateway_integrations_resource,
      local.application_apigateway_integration_resource_prefix,
      local.application_apigateway_routes_resource,
      local.application_apigateway_route_resource_prefix,
      local.application_apigateway_stages_resource,
      local.application_apigateway_stage_resource_prefix,
      local.application_apigateway_api_tag_resource,
    ]
  }

  statement {
    sid    = "DescribeCloudWatchAlarmMetrics"
    effect = "Allow"

    actions = [
      "cloudwatch:DescribeAlarmsForMetric",
    ]

    resources = [
      "*",
    ]
  }

  statement {
    sid    = "ManageCloudWatchAlarms"
    effect = "Allow"

    actions = [
      "cloudwatch:DeleteAlarms",
      "cloudwatch:DescribeAlarms",
      "cloudwatch:ListTagsForResource",
      "cloudwatch:PutMetricAlarm",
      "cloudwatch:TagResource",
      "cloudwatch:UntagResource",
    ]

    resources = [
      local.application_alarm_arn_prefix,
    ]
  }

  statement {
    sid    = "ListCloudWatchDashboards"
    effect = "Allow"

    actions = [
      "cloudwatch:ListDashboards",
    ]

    resources = [
      "*",
    ]
  }

  statement {
    sid    = "ManageCloudWatchDashboard"
    effect = "Allow"

    actions = [
      "cloudwatch:DeleteDashboards",
      "cloudwatch:GetDashboard",
      "cloudwatch:PutDashboard",
    ]

    resources = [
      local.operations_dashboard_arn,
    ]
  }

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
    sid    = "ManageCloudWatchLogGroups"
    effect = "Allow"

    actions = [
      "logs:CreateLogGroup",
      "logs:DeleteLogGroup",
      "logs:DeleteRetentionPolicy",
      "logs:PutRetentionPolicy",
    ]

    resources = local.application_log_group_management_arns
  }

  statement {
    sid    = "ManageCloudWatchLogGroupTags"
    effect = "Allow"

    actions = [
      "logs:ListTagsForResource",
      "logs:TagResource",
      "logs:UntagResource",
    ]

    resources = local.application_log_group_arns
  }

  statement {
    sid    = "ManageDynamoDBTableControlPlane"
    effect = "Allow"

    actions = [
      "dynamodb:CreateTable",
      "dynamodb:DeleteTable",
      "dynamodb:DescribeContinuousBackups",
      "dynamodb:DescribeContributorInsights",
      "dynamodb:DescribeTable",
      "dynamodb:DescribeTimeToLive",
      "dynamodb:ListTagsOfResource",
      "dynamodb:TagResource",
      "dynamodb:UntagResource",
      "dynamodb:UpdateContinuousBackups",
      "dynamodb:UpdateTable",
      "dynamodb:UpdateTimeToLive",
    ]

    resources = [
      local.document_jobs_table_arn,
    ]
  }

  statement {
    sid    = "ManageLambdaExecutionRoles"
    effect = "Allow"

    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetRole",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
      "iam:ListRoleTags",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:UpdateRole",
      "iam:UpdateRoleDescription",
    ]

    resources = local.lambda_execution_role_arns
  }

  statement {
    sid    = "ManageLambdaExecutionRoleInlinePolicies"
    effect = "Allow"

    actions = [
      "iam:DeleteRolePolicy",
      "iam:GetRolePolicy",
      "iam:ListRolePolicies",
      "iam:PutRolePolicy",
    ]

    resources = local.lambda_execution_role_arns
  }

  statement {
    sid    = "PassOnlyLambdaExecutionRolesToLambdaService"
    effect = "Allow"

    actions = [
      "iam:PassRole",
    ]

    resources = local.lambda_execution_role_arns

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"

      values = [
        "lambda.amazonaws.com",
      ]
    }
  }

  statement {
    sid    = "ManageLambdaFunctions"
    effect = "Allow"

    actions = [
      "lambda:CreateFunction",
      "lambda:DeleteFunction",
      "lambda:GetFunction",
      "lambda:GetFunctionCodeSigningConfig",
      "lambda:GetFunctionConcurrency",
      "lambda:GetFunctionConfiguration",
      "lambda:GetFunctionEventInvokeConfig",
      "lambda:GetPolicy",
      "lambda:GetRuntimeManagementConfig",
      "lambda:ListFunctionEventInvokeConfigs",
      "lambda:ListTags",
      "lambda:ListVersionsByFunction",
      "lambda:TagResource",
      "lambda:UntagResource",
      "lambda:UpdateFunctionCode",
      "lambda:UpdateFunctionConfiguration",
    ]

    resources = local.application_lambda_function_arns
  }

  statement {
    sid    = "ManageLambdaPermissions"
    effect = "Allow"

    actions = [
      "lambda:AddPermission",
      "lambda:GetPolicy",
      "lambda:RemovePermission",
    ]

    resources = local.application_lambda_function_arns
  }

  statement {
    sid    = "ListLambdaEventSourceMappings"
    effect = "Allow"

    actions = [
      "lambda:ListEventSourceMappings",
    ]

    resources = [
      "*",
    ]
  }

  statement {
    sid    = "ManageLambdaEventSourceMappings"
    effect = "Allow"

    actions = [
      "lambda:CreateEventSourceMapping",
      "lambda:DeleteEventSourceMapping",
      "lambda:GetEventSourceMapping",
      "lambda:UpdateEventSourceMapping",
    ]

    resources = [
      local.application_lambda_event_source_mapping_arn_prefix,
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
    sid    = "ManageDocumentsBucketControlPlane"
    effect = "Allow"

    actions = [
      "s3:CreateBucket",
      "s3:DeleteBucket",
      "s3:DeleteBucketPolicy",
      "s3:PutBucketNotification",
      "s3:PutBucketOwnershipControls",
      "s3:PutBucketPolicy",
      "s3:PutBucketPublicAccessBlock",
      "s3:PutBucketTagging",
      "s3:PutBucketVersioning",
      "s3:PutEncryptionConfiguration",
      "s3:PutLifecycleConfiguration",
    ]

    resources = [
      local.documents_bucket_arn,
    ]
  }

  statement {
    sid    = "ManageApplicationSqsQueues"
    effect = "Allow"

    actions = [
      "sqs:CreateQueue",
      "sqs:DeleteQueue",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
      "sqs:ListQueueTags",
      "sqs:SetQueueAttributes",
      "sqs:TagQueue",
      "sqs:UntagQueue",
    ]

    resources = local.application_sqs_queue_arns
  }
}

resource "aws_iam_role_policy" "terraform_apply_access" {
  name   = local.terraform_apply_policy_name
  role   = aws_iam_role.terraform_apply.name
  policy = data.aws_iam_policy_document.terraform_apply_access.json
}
