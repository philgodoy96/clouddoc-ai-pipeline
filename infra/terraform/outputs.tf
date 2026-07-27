output "documents_bucket_name" {
  description = "Name of the private source-document bucket."
  value       = aws_s3_bucket.documents.bucket
}

output "documents_bucket_arn" {
  description = "ARN of the private source-document bucket."
  value       = aws_s3_bucket.documents.arn
}

output "processing_queue_name" {
  description = "Name of the processing source queue."
  value       = aws_sqs_queue.processing.name
}

output "processing_queue_arn" {
  description = "ARN of the processing source queue."
  value       = aws_sqs_queue.processing.arn
}

output "processing_queue_url" {
  description = "URL of the processing source queue."
  value       = aws_sqs_queue.processing.url
}

output "processing_dlq_name" {
  description = "Name of the processing dead-letter queue."
  value       = aws_sqs_queue.processing_dlq.name
}

output "processing_dlq_arn" {
  description = "ARN of the processing dead-letter queue."
  value       = aws_sqs_queue.processing_dlq.arn
}

output "processing_dlq_url" {
  description = "URL of the processing dead-letter queue."
  value       = aws_sqs_queue.processing_dlq.url
}

output "reconciliation_failures_queue_name" {
  description = "Name of the terminal dead-letter reconciliation quarantine queue."
  value       = aws_sqs_queue.reconciliation_failures.name
}

output "reconciliation_failures_queue_arn" {
  description = "ARN of the terminal dead-letter reconciliation quarantine queue."
  value       = aws_sqs_queue.reconciliation_failures.arn
}

output "reconciliation_failures_queue_url" {
  description = "URL of the terminal dead-letter reconciliation quarantine queue."
  value       = aws_sqs_queue.reconciliation_failures.url
}

output "document_jobs_table_name" {
  description = "Name of the authoritative document-jobs table."
  value       = aws_dynamodb_table.document_jobs.name
}

output "document_jobs_table_arn" {
  description = "ARN of the authoritative document-jobs table."
  value       = aws_dynamodb_table.document_jobs.arn
}

output "create_job_function_name" {
  description = "Name of the Create Job Lambda function."
  value       = aws_lambda_function.create_job.function_name
}

output "create_job_function_arn" {
  description = "ARN of the Create Job Lambda function."
  value       = aws_lambda_function.create_job.arn
}

output "get_job_function_name" {
  description = "Name of the Get Job Lambda function."
  value       = aws_lambda_function.get_job.function_name
}

output "get_job_function_arn" {
  description = "ARN of the Get Job Lambda function."
  value       = aws_lambda_function.get_job.arn
}

output "processor_function_name" {
  description = "Name of the Document Processor Lambda function."
  value       = aws_lambda_function.processor.function_name
}

output "processor_function_arn" {
  description = "ARN of the Document Processor Lambda function."
  value       = aws_lambda_function.processor.arn
}

output "dead_letter_reconciler_function_name" {
  description = "Name of the Dead-Letter Reconciler Lambda function."
  value       = aws_lambda_function.dead_letter_reconciler.function_name
}

output "dead_letter_reconciler_function_arn" {
  description = "ARN of the Dead-Letter Reconciler Lambda function."
  value       = aws_lambda_function.dead_letter_reconciler.arn
}

output "control_plane_api_id" {
  description = "Identifier of the CloudDoc HTTP control-plane API."
  value       = aws_apigatewayv2_api.control_plane.id
}

output "control_plane_api_execution_arn" {
  description = "Execution ARN prefix of the CloudDoc HTTP control-plane API."
  value       = aws_apigatewayv2_api.control_plane.execution_arn
}

output "control_plane_api_base_url" {
  description = "Environment-stage base URL of the CloudDoc HTTP control-plane API."
  value       = "${aws_apigatewayv2_api.control_plane.api_endpoint}/${aws_apigatewayv2_stage.control_plane.name}"
}

output "control_plane_api_stage_name" {
  description = "Name of the deployed CloudDoc HTTP control-plane API stage."
  value       = aws_apigatewayv2_stage.control_plane.name
}

output "control_plane_api_access_log_group_name" {
  description = "Name of the CloudDoc HTTP control-plane API access-log group."
  value       = aws_cloudwatch_log_group.control_plane_api_access.name
}

output "operations_dashboard_name" {
  description = "Name of the CloudDoc operational CloudWatch dashboard."
  value       = aws_cloudwatch_dashboard.operations.dashboard_name
}
