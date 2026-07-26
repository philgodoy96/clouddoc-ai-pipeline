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

output "document_jobs_table_name" {
  description = "Name of the authoritative document-jobs table."
  value       = aws_dynamodb_table.document_jobs.name
}

output "document_jobs_table_arn" {
  description = "ARN of the authoritative document-jobs table."
  value       = aws_dynamodb_table.document_jobs.arn
}
