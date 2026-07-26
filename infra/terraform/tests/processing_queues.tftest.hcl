mock_provider "aws" {
  override_during = plan
}

variables {
  aws_region   = "us-east-1"
  project_name = "clouddoc"
  environment  = "dev"
}

override_data {
  target          = data.aws_caller_identity.current
  override_during = plan

  values = {
    account_id = "123456789012"
  }
}

override_resource {
  target          = aws_sqs_queue.processing
  override_during = plan

  values = {
    arn = "arn:aws:sqs:us-east-1:123456789012:clouddoc-dev-processing"
    url = "https://sqs.us-east-1.amazonaws.com/123456789012/clouddoc-dev-processing"
  }
}

override_resource {
  target          = aws_sqs_queue.processing_dlq
  override_during = plan

  values = {
    arn = "arn:aws:sqs:us-east-1:123456789012:clouddoc-dev-processing-dlq"
    url = "https://sqs.us-east-1.amazonaws.com/123456789012/clouddoc-dev-processing-dlq"
  }
}

run "processing_queue_topology" {
  command = plan

  assert {
    condition     = local.name_prefix == "clouddoc-dev"
    error_message = "The resource name prefix must include the project and environment."
  }

  assert {
    condition     = local.common_tags["Project"] == "clouddoc"
    error_message = "The shared Project tag must match the configured project name."
  }

  assert {
    condition     = local.common_tags["Environment"] == "dev"
    error_message = "The shared Environment tag must match the configured environment."
  }

  assert {
    condition     = local.common_tags["ManagedBy"] == "terraform"
    error_message = "CloudDoc infrastructure must be tagged as Terraform-managed."
  }

  assert {
    condition     = local.common_tags["Component"] == "document-processing"
    error_message = "The shared Component tag must identify document processing."
  }

  assert {
    condition     = aws_sqs_queue.processing.name == "clouddoc-dev-processing"
    error_message = "The processing queue name must be environment-scoped."
  }

  assert {
    condition     = aws_sqs_queue.processing.fifo_queue == false
    error_message = "The processing queue must be a Standard queue."
  }

  assert {
    condition     = aws_sqs_queue.processing.delay_seconds == 0
    error_message = "The processing queue must not delay newly published messages."
  }

  assert {
    condition     = aws_sqs_queue.processing.visibility_timeout_seconds == 720
    error_message = "The processing queue visibility timeout must be 720 seconds."
  }

  assert {
    condition     = aws_sqs_queue.processing.message_retention_seconds == 345600
    error_message = "The processing queue must retain messages for four days."
  }

  assert {
    condition     = aws_sqs_queue.processing.sqs_managed_sse_enabled
    error_message = "The processing queue must use SQS-managed encryption."
  }

  assert {
    condition     = aws_sqs_queue.processing.tags["Name"] == "clouddoc-dev-processing"
    error_message = "The processing queue Name tag must match its queue name."
  }

  assert {
    condition     = aws_sqs_queue.processing.tags["QueueRole"] == "processing-source"
    error_message = "The processing queue must be tagged as the processing source."
  }

  assert {
    condition     = aws_sqs_queue.processing_dlq.name == "clouddoc-dev-processing-dlq"
    error_message = "The processing DLQ name must be environment-scoped."
  }

  assert {
    condition     = aws_sqs_queue.processing_dlq.fifo_queue == false
    error_message = "The processing DLQ must be a Standard queue."
  }

  assert {
    condition     = aws_sqs_queue.processing_dlq.delay_seconds == 0
    error_message = "The processing DLQ must not apply a delivery delay."
  }

  assert {
    condition     = aws_sqs_queue.processing_dlq.visibility_timeout_seconds == 180
    error_message = "The processing DLQ visibility timeout must be 180 seconds."
  }

  assert {
    condition     = aws_sqs_queue.processing_dlq.message_retention_seconds == 1209600
    error_message = "The processing DLQ must retain messages for fourteen days."
  }

  assert {
    condition     = aws_sqs_queue.processing_dlq.sqs_managed_sse_enabled
    error_message = "The processing DLQ must use SQS-managed encryption."
  }

  assert {
    condition     = aws_sqs_queue.processing_dlq.tags["Name"] == "clouddoc-dev-processing-dlq"
    error_message = "The processing DLQ Name tag must match its queue name."
  }

  assert {
    condition     = aws_sqs_queue.processing_dlq.tags["QueueRole"] == "processing-dead-letter"
    error_message = "The processing DLQ must be tagged as the dead-letter destination."
  }

  assert {
    condition = (
      aws_sqs_queue.processing_dlq.message_retention_seconds >
      aws_sqs_queue.processing.message_retention_seconds
    )
    error_message = "The processing DLQ retention must exceed the source queue retention."
  }

  assert {
    condition = (
      aws_sqs_queue_redrive_policy.processing.queue_url ==
      aws_sqs_queue.processing.url
    )
    error_message = "The redrive policy must be attached to the processing queue."
  }

  assert {
    condition = (
      jsondecode(
        aws_sqs_queue_redrive_policy.processing.redrive_policy
      ).deadLetterTargetArn ==
      aws_sqs_queue.processing_dlq.arn
    )
    error_message = "The processing queue must redrive exhausted messages to its dedicated DLQ."
  }

  assert {
    condition = (
      jsondecode(
        aws_sqs_queue_redrive_policy.processing.redrive_policy
      ).maxReceiveCount == 3
    )
    error_message = "The processing queue must redrive messages after three receives."
  }

  assert {
    condition = (
      aws_sqs_queue_redrive_allow_policy.processing_dlq.queue_url ==
      aws_sqs_queue.processing_dlq.url
    )
    error_message = "The redrive allow policy must be attached to the processing DLQ."
  }

  assert {
    condition = (
      jsondecode(
        aws_sqs_queue_redrive_allow_policy.processing_dlq.redrive_allow_policy
      ).redrivePermission == "byQueue"
    )
    error_message = "The processing DLQ must restrict access by source queue."
  }

  assert {
    condition = (
      length(
        jsondecode(
          aws_sqs_queue_redrive_allow_policy.processing_dlq.redrive_allow_policy
        ).sourceQueueArns
      ) == 1
    )
    error_message = "The processing DLQ must permit exactly one source queue."
  }

  assert {
    condition = (
      jsondecode(
        aws_sqs_queue_redrive_allow_policy.processing_dlq.redrive_allow_policy
      ).sourceQueueArns[0] ==
      aws_sqs_queue.processing.arn
    )
    error_message = "Only the CloudDoc processing queue may use the processing DLQ."
  }

  assert {
    condition     = output.processing_queue_name == aws_sqs_queue.processing.name
    error_message = "The processing queue name output must reference the processing queue."
  }

  assert {
    condition     = output.processing_queue_arn == aws_sqs_queue.processing.arn
    error_message = "The processing queue ARN output must reference the processing queue."
  }

  assert {
    condition     = output.processing_queue_url == aws_sqs_queue.processing.url
    error_message = "The processing queue URL output must reference the processing queue."
  }

  assert {
    condition     = output.processing_dlq_name == aws_sqs_queue.processing_dlq.name
    error_message = "The processing DLQ name output must reference the processing DLQ."
  }

  assert {
    condition     = output.processing_dlq_arn == aws_sqs_queue.processing_dlq.arn
    error_message = "The processing DLQ ARN output must reference the processing DLQ."
  }

  assert {
    condition     = output.processing_dlq_url == aws_sqs_queue.processing_dlq.url
    error_message = "The processing DLQ URL output must reference the processing DLQ."
  }
}

run "environment_scoped_queue_names" {
  command = plan

  variables {
    environment = "staging"
  }

  assert {
    condition     = local.name_prefix == "clouddoc-staging"
    error_message = "Changing the environment must change the shared name prefix."
  }

  assert {
    condition     = aws_sqs_queue.processing.name == "clouddoc-staging-processing"
    error_message = "The processing queue name must change with the environment."
  }

  assert {
    condition     = aws_sqs_queue.processing_dlq.name == "clouddoc-staging-processing-dlq"
    error_message = "The processing DLQ name must change with the environment."
  }

  assert {
    condition     = local.common_tags["Environment"] == "staging"
    error_message = "The shared Environment tag must change with the environment."
  }
}