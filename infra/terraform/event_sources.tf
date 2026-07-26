resource "aws_lambda_event_source_mapping" "processing_queue" {
  event_source_arn = aws_sqs_queue.processing.arn
  function_name    = aws_lambda_function.processor.arn
  enabled          = true

  batch_size                         = 1
  maximum_batching_window_in_seconds = 0

  function_response_types = [
    "ReportBatchItemFailures",
  ]

  scaling_config {
    maximum_concurrency = 5
  }

  depends_on = [
    aws_iam_role_policy.processor_queue_consumer,
  ]
}