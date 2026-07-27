resource "aws_lambda_function" "create_job" {
  function_name = local.create_job_function_name
  description   = "Creates an authoritative CloudDoc document job and returns a presigned upload URL."

  role    = aws_iam_role.create_job.arn
  handler = "clouddoc.handlers.create_job.lambda_handler"

  runtime       = "python3.12"
  architectures = ["x86_64"]
  package_type  = "Zip"
  publish       = false

  filename         = local.lambda_artifact_path
  source_code_hash = local.lambda_source_code_hash

  memory_size = 256
  timeout     = 10

  environment {
    variables = local.lambda_runtime_environment
  }

  logging_config {
    log_format = "JSON"
  }

  tags = {
    Name         = local.create_job_function_name
    FunctionRole = "create-job"
  }

  depends_on = [
    aws_cloudwatch_log_group.create_job,
    aws_iam_role_policy.create_job_logging,
    aws_iam_role_policy.create_job_permissions,
  ]
}

resource "aws_lambda_function" "get_job" {
  function_name = local.get_job_function_name
  description   = "Retrieves one authoritative CloudDoc document job."

  role    = aws_iam_role.get_job.arn
  handler = "clouddoc.handlers.get_job.lambda_handler"

  runtime       = "python3.12"
  architectures = ["x86_64"]
  package_type  = "Zip"
  publish       = false

  filename         = local.lambda_artifact_path
  source_code_hash = local.lambda_source_code_hash

  memory_size = 256
  timeout     = 5

  environment {
    variables = local.lambda_runtime_environment
  }

  logging_config {
    log_format = "JSON"
  }

  tags = {
    Name         = local.get_job_function_name
    FunctionRole = "get-job"
  }

  depends_on = [
    aws_cloudwatch_log_group.get_job,
    aws_iam_role_policy.get_job_logging,
    aws_iam_role_policy.get_job_permissions,
  ]
}

resource "aws_lambda_function" "processor" {
  function_name = local.processor_function_name
  description   = "Processes uploaded CloudDoc source documents and persists attempt-aware job outcomes."

  role    = aws_iam_role.processor.arn
  handler = "clouddoc.handlers.process_uploaded_document.lambda_handler"

  runtime       = "python3.12"
  architectures = ["x86_64"]
  package_type  = "Zip"
  publish       = false

  filename         = local.lambda_artifact_path
  source_code_hash = local.lambda_source_code_hash

  memory_size = 1024
  timeout     = 120

  environment {
    variables = local.processor_runtime_environment
  }

  logging_config {
    log_format = "JSON"
  }

  tags = {
    Name         = local.processor_function_name
    FunctionRole = "document-processor"
  }

  depends_on = [
    aws_cloudwatch_log_group.processor,
    aws_iam_role_policy.processor_logging,
    aws_iam_role_policy.processor_permissions,
    aws_iam_role_policy.processor_bedrock_invoke,
  ]
}

resource "aws_lambda_function" "dead_letter_reconciler" {
  function_name = local.dead_letter_reconciler_function_name
  description   = "Reconciles exhausted document deliveries into authoritative CloudDoc job state."

  role    = aws_iam_role.dead_letter_reconciler.arn
  handler = "clouddoc.handlers.reconcile_dead_lettered_document.lambda_handler"

  runtime       = "python3.12"
  architectures = ["x86_64"]
  package_type  = "Zip"
  publish       = false

  filename         = local.lambda_artifact_path
  source_code_hash = local.lambda_source_code_hash

  memory_size = 512
  timeout     = 30

  environment {
    variables = local.lambda_runtime_environment
  }

  logging_config {
    log_format = "JSON"
  }

  tags = {
    Name         = local.dead_letter_reconciler_function_name
    FunctionRole = "dead-letter-reconciler"
  }

  depends_on = [
    aws_cloudwatch_log_group.dead_letter_reconciler,
    aws_iam_role_policy.dead_letter_reconciler_logging,
    aws_iam_role_policy.dead_letter_reconciler_permissions,
  ]
}