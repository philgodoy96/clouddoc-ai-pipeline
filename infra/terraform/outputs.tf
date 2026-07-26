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