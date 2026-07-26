resource "aws_cloudwatch_log_group" "create_job" {
  name              = "/aws/lambda/${local.create_job_function_name}"
  retention_in_days = local.lambda_log_retention_days

  tags = {
    Name         = "/aws/lambda/${local.create_job_function_name}"
    LogRole      = "lambda-runtime"
    FunctionRole = "create-job"
  }
}

resource "aws_cloudwatch_log_group" "get_job" {
  name              = "/aws/lambda/${local.get_job_function_name}"
  retention_in_days = local.lambda_log_retention_days

  tags = {
    Name         = "/aws/lambda/${local.get_job_function_name}"
    LogRole      = "lambda-runtime"
    FunctionRole = "get-job"
  }
}

resource "aws_cloudwatch_log_group" "processor" {
  name              = "/aws/lambda/${local.processor_function_name}"
  retention_in_days = local.lambda_log_retention_days

  tags = {
    Name         = "/aws/lambda/${local.processor_function_name}"
    LogRole      = "lambda-runtime"
    FunctionRole = "document-processor"
  }
}

resource "aws_cloudwatch_log_group" "dead_letter_reconciler" {
  name              = "/aws/lambda/${local.dead_letter_reconciler_function_name}"
  retention_in_days = local.lambda_log_retention_days

  tags = {
    Name         = "/aws/lambda/${local.dead_letter_reconciler_function_name}"
    LogRole      = "lambda-runtime"
    FunctionRole = "dead-letter-reconciler"
  }
}