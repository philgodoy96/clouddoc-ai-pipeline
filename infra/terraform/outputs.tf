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
