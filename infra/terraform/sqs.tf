resource "aws_sqs_queue" "processing_dlq" {
  name = "${local.name_prefix}-processing-dlq"

  fifo_queue                 = false
  delay_seconds              = 0
  visibility_timeout_seconds = 180
  message_retention_seconds  = 1209600
  sqs_managed_sse_enabled    = true

  tags = {
    Name      = "${local.name_prefix}-processing-dlq"
    QueueRole = "processing-dead-letter"
  }
}

resource "aws_sqs_queue" "processing" {
  name = "${local.name_prefix}-processing"

  fifo_queue                 = false
  delay_seconds              = 0
  visibility_timeout_seconds = 720
  message_retention_seconds  = 345600
  sqs_managed_sse_enabled    = true

  tags = {
    Name      = "${local.name_prefix}-processing"
    QueueRole = "processing-source"
  }
}

resource "aws_sqs_queue_redrive_policy" "processing" {
  queue_url = aws_sqs_queue.processing.url

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.processing_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_sqs_queue_redrive_allow_policy" "processing_dlq" {
  queue_url = aws_sqs_queue.processing_dlq.url

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns = [
      aws_sqs_queue.processing.arn,
    ]
  })
}
