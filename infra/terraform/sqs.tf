resource "aws_sqs_queue" "processing_dlq" {
  name = "${local.name_prefix}-processing-dlq"

  fifo_queue                  = false
  delay_seconds               = 0
  visibility_timeout_seconds  = 180
  message_retention_seconds   = 1209600
  sqs_managed_sse_enabled     = true

  tags = {
    Name      = "${local.name_prefix}-processing-dlq"
    QueueRole = "processing-dead-letter"
  }
}