data "aws_iam_policy_document" "lambda_assume_role" {
  version = "2012-10-17"

  statement {
    sid    = "AllowLambdaServiceAssumeRole"
    effect = "Allow"

    actions = [
      "sts:AssumeRole",
    ]

    principals {
      type = "Service"

      identifiers = [
        "lambda.amazonaws.com",
      ]
    }
  }
}

resource "aws_iam_role" "create_job" {
  name               = "${local.create_job_function_name}-role"
  description        = "Execution role for the CloudDoc create-job Lambda function."
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Name         = "${local.create_job_function_name}-role"
    RolePurpose  = "lambda-execution"
    FunctionRole = "create-job"
  }
}

resource "aws_iam_role" "get_job" {
  name               = "${local.get_job_function_name}-role"
  description        = "Execution role for the CloudDoc get-job Lambda function."
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Name         = "${local.get_job_function_name}-role"
    RolePurpose  = "lambda-execution"
    FunctionRole = "get-job"
  }
}

resource "aws_iam_role" "processor" {
  name               = "${local.processor_function_name}-role"
  description        = "Execution role for the CloudDoc document-processor Lambda function."
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Name         = "${local.processor_function_name}-role"
    RolePurpose  = "lambda-execution"
    FunctionRole = "document-processor"
  }
}

resource "aws_iam_role" "dead_letter_reconciler" {
  name               = "${local.dead_letter_reconciler_function_name}-role"
  description        = "Execution role for the CloudDoc dead-letter reconciler Lambda function."
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Name         = "${local.dead_letter_reconciler_function_name}-role"
    RolePurpose  = "lambda-execution"
    FunctionRole = "dead-letter-reconciler"
  }
}

data "aws_iam_policy_document" "create_job_logging" {
  version = "2012-10-17"

  statement {
    sid    = "WriteCreateJobLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]

    resources = [
      "${aws_cloudwatch_log_group.create_job.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "create_job_logging" {
  name   = "${local.create_job_function_name}-logging"
  role   = aws_iam_role.create_job.id
  policy = data.aws_iam_policy_document.create_job_logging.json
}

data "aws_iam_policy_document" "get_job_logging" {
  version = "2012-10-17"

  statement {
    sid    = "WriteGetJobLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]

    resources = [
      "${aws_cloudwatch_log_group.get_job.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "get_job_logging" {
  name   = "${local.get_job_function_name}-logging"
  role   = aws_iam_role.get_job.id
  policy = data.aws_iam_policy_document.get_job_logging.json
}

data "aws_iam_policy_document" "processor_logging" {
  version = "2012-10-17"

  statement {
    sid    = "WriteProcessorLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]

    resources = [
      "${aws_cloudwatch_log_group.processor.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "processor_logging" {
  name   = "${local.processor_function_name}-logging"
  role   = aws_iam_role.processor.id
  policy = data.aws_iam_policy_document.processor_logging.json
}

data "aws_iam_policy_document" "dead_letter_reconciler_logging" {
  version = "2012-10-17"

  statement {
    sid    = "WriteDeadLetterReconcilerLogs"
    effect = "Allow"

    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]

    resources = [
      "${aws_cloudwatch_log_group.dead_letter_reconciler.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "dead_letter_reconciler_logging" {
  name   = "${local.dead_letter_reconciler_function_name}-logging"
  role   = aws_iam_role.dead_letter_reconciler.id
  policy = data.aws_iam_policy_document.dead_letter_reconciler_logging.json
}

data "aws_iam_policy_document" "create_job_permissions" {
  version = "2012-10-17"

  statement {
    sid    = "CreateDocumentJob"
    effect = "Allow"

    actions = [
      "dynamodb:PutItem",
    ]

    resources = [
      aws_dynamodb_table.document_jobs.arn,
    ]
  }

  statement {
    sid    = "AuthorizeCanonicalDocumentUpload"
    effect = "Allow"

    actions = [
      "s3:PutObject",
    ]

    resources = [
      "${aws_s3_bucket.documents.arn}/documents/*",
    ]
  }
}

resource "aws_iam_role_policy" "create_job_permissions" {
  name   = "${local.create_job_function_name}-permissions"
  role   = aws_iam_role.create_job.id
  policy = data.aws_iam_policy_document.create_job_permissions.json
}

data "aws_iam_policy_document" "get_job_permissions" {
  version = "2012-10-17"

  statement {
    sid    = "ReadDocumentJob"
    effect = "Allow"

    actions = [
      "dynamodb:GetItem",
    ]

    resources = [
      aws_dynamodb_table.document_jobs.arn,
    ]
  }
}

resource "aws_iam_role_policy" "get_job_permissions" {
  name   = "${local.get_job_function_name}-permissions"
  role   = aws_iam_role.get_job.id
  policy = data.aws_iam_policy_document.get_job_permissions.json
}

data "aws_iam_policy_document" "processor_permissions" {
  version = "2012-10-17"

  statement {
    sid    = "ReadAndPersistDocumentJob"
    effect = "Allow"

    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
    ]

    resources = [
      aws_dynamodb_table.document_jobs.arn,
    ]
  }

  statement {
    sid    = "ReadCanonicalDocumentObject"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
    ]

    resources = [
      "${aws_s3_bucket.documents.arn}/documents/*",
    ]
  }
}

resource "aws_iam_role_policy" "processor_permissions" {
  name   = "${local.processor_function_name}-permissions"
  role   = aws_iam_role.processor.id
  policy = data.aws_iam_policy_document.processor_permissions.json
}

data "aws_iam_policy_document" "processor_queue_consumer" {
  version = "2012-10-17"

  statement {
    sid    = "ConsumeProcessingQueue"
    effect = "Allow"

    actions = [
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ReceiveMessage",
    ]

    resources = [
      aws_sqs_queue.processing.arn,
    ]
  }
}

resource "aws_iam_role_policy" "processor_queue_consumer" {
  name   = "${local.processor_function_name}-processing-queue"
  role   = aws_iam_role.processor.id
  policy = data.aws_iam_policy_document.processor_queue_consumer.json
}

data "aws_iam_policy_document" "dead_letter_reconciler_permissions" {
  version = "2012-10-17"

  statement {
    sid    = "ReadAndPersistDeadLetterJobState"
    effect = "Allow"

    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
    ]

    resources = [
      aws_dynamodb_table.document_jobs.arn,
    ]
  }
}

resource "aws_iam_role_policy" "dead_letter_reconciler_permissions" {
  name   = "${local.dead_letter_reconciler_function_name}-permissions"
  role   = aws_iam_role.dead_letter_reconciler.id
  policy = data.aws_iam_policy_document.dead_letter_reconciler_permissions.json
}