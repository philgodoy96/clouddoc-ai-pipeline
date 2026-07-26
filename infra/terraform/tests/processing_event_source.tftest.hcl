mock_provider "aws" {
  override_during = plan

  # mock_provider invents a random string for computed .json; IAM resources
  # validate policy JSON, so supply a minimal valid rendered document.
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
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
  target          = aws_s3_bucket.documents
  override_during = plan

  values = {
    id     = "clouddoc-dev-123456789012-documents"
    arn    = "arn:aws:s3:::clouddoc-dev-123456789012-documents"
    bucket = "clouddoc-dev-123456789012-documents"
  }
}

override_resource {
  target          = aws_dynamodb_table.document_jobs
  override_during = plan

  values = {
    id   = "clouddoc-dev-document-jobs"
    name = "clouddoc-dev-document-jobs"
    arn  = "arn:aws:dynamodb:us-east-1:123456789012:table/clouddoc-dev-document-jobs"
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

override_resource {
  target          = aws_cloudwatch_log_group.create_job
  override_during = plan

  values = {
    arn = "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/clouddoc-dev-create-job"
  }
}

override_resource {
  target          = aws_cloudwatch_log_group.get_job
  override_during = plan

  values = {
    arn = "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/clouddoc-dev-get-job"
  }
}

override_resource {
  target          = aws_cloudwatch_log_group.processor
  override_during = plan

  values = {
    arn = "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/clouddoc-dev-process-document"
  }
}

override_resource {
  target          = aws_cloudwatch_log_group.dead_letter_reconciler
  override_during = plan

  values = {
    arn = "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/clouddoc-dev-reconcile-dead-letter"
  }
}

override_resource {
  target          = aws_iam_role.create_job
  override_during = plan

  values = {
    id  = "clouddoc-dev-create-job-role"
    arn = "arn:aws:iam::123456789012:role/clouddoc-dev-create-job-role"
  }
}

override_resource {
  target          = aws_iam_role.get_job
  override_during = plan

  values = {
    id  = "clouddoc-dev-get-job-role"
    arn = "arn:aws:iam::123456789012:role/clouddoc-dev-get-job-role"
  }
}

override_resource {
  target          = aws_iam_role.processor
  override_during = plan

  values = {
    id  = "clouddoc-dev-process-document-role"
    arn = "arn:aws:iam::123456789012:role/clouddoc-dev-process-document-role"
  }
}

override_resource {
  target          = aws_iam_role.dead_letter_reconciler
  override_during = plan

  values = {
    id  = "clouddoc-dev-reconcile-dead-letter-role"
    arn = "arn:aws:iam::123456789012:role/clouddoc-dev-reconcile-dead-letter-role"
  }
}

override_resource {
  target          = aws_lambda_function.create_job
  override_during = plan

  values = {
    function_name = "clouddoc-dev-create-job"
    arn           = "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-create-job"
  }
}

override_resource {
  target          = aws_lambda_function.get_job
  override_during = plan

  values = {
    function_name = "clouddoc-dev-get-job"
    arn           = "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-get-job"
  }
}

override_resource {
  target          = aws_lambda_function.processor
  override_during = plan

  values = {
    function_name = "clouddoc-dev-process-document"
    arn           = "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-process-document"
  }
}

override_resource {
  target          = aws_lambda_function.dead_letter_reconciler
  override_during = plan

  values = {
    function_name = "clouddoc-dev-reconcile-dead-letter"
    arn           = "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-reconcile-dead-letter"
  }
}

run "processor_queue_consumer_permissions" {
  command = plan

  assert {
    condition = (
      length(
        data.aws_iam_policy_document
        .processor_queue_consumer.statement
      ) ==
      1
    )
    error_message = "The Processor queue-consumer policy must contain exactly one statement."
  }

  assert {
    condition = (
      one(
        data.aws_iam_policy_document
        .processor_queue_consumer.statement
      ).sid ==
      "ConsumeProcessingQueue"
    )
    error_message = "The Processor queue-consumer permission must use the expected statement identifier."
  }

  assert {
    condition = (
      one(
        data.aws_iam_policy_document
        .processor_queue_consumer.statement
      ).effect ==
      "Allow"
    )
    error_message = "The Processor queue-consumer statement must explicitly allow queue consumption."
  }

  assert {
    condition = (
      toset(
        one(
          data.aws_iam_policy_document
          .processor_queue_consumer.statement
        ).actions
      ) ==
      toset([
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:ReceiveMessage",
      ])
    )
    error_message = "The Processor must receive exactly the required SQS consumer actions."
  }

  assert {
    condition = (
      toset(
        one(
          data.aws_iam_policy_document
          .processor_queue_consumer.statement
        ).resources
      ) ==
      toset([
        aws_sqs_queue.processing.arn,
      ])
    )
    error_message = "The Processor SQS policy must target only the processing queue."
  }

  assert {
    condition = (
      !contains(
        one(
          data.aws_iam_policy_document
          .processor_queue_consumer.statement
        ).resources,
        aws_sqs_queue.processing_dlq.arn,
      ) &&
      !contains(
        one(
          data.aws_iam_policy_document
          .processor_queue_consumer.statement
        ).resources,
        "*",
      )
    )
    error_message = "The Processor must not receive DLQ or wildcard SQS access."
  }

  assert {
    condition = (
      aws_iam_role_policy.processor_queue_consumer.role ==
      aws_iam_role.processor.id
    )
    error_message = "The processing-queue consumer policy must be attached to the Processor role."
  }

  assert {
    condition = (
      aws_iam_role_policy.processor_queue_consumer.name ==
      "${local.processor_function_name}-processing-queue"
    )
    error_message = "The Processor must use a dedicated processing-queue consumer inline policy."
  }
}

run "processing_event_source_topology" {
  command = plan

  assert {
    condition = (
      aws_lambda_event_source_mapping.processing_queue.event_source_arn ==
      aws_sqs_queue.processing.arn
    )
    error_message = "The event source mapping must consume the processing queue."
  }

  assert {
    condition = (
      aws_lambda_event_source_mapping.processing_queue.function_name ==
      aws_lambda_function.processor.arn
    )
    error_message = "The processing queue must target only the Document Processor Lambda."
  }

  assert {
    condition = (
      aws_lambda_event_source_mapping.processing_queue.enabled
    )
    error_message = "The processing queue event source mapping must be enabled."
  }

  assert {
    condition = (
      aws_lambda_event_source_mapping.processing_queue.batch_size ==
      1
    )
    error_message = "Each Processor invocation must receive at most one document message."
  }

  assert {
    condition = (
      aws_lambda_event_source_mapping.processing_queue
      .maximum_batching_window_in_seconds ==
      0
    )
    error_message = "The processing event source must not delay invocation to accumulate a batch."
  }

  assert {
    condition = (
      toset(
        aws_lambda_event_source_mapping
        .processing_queue.function_response_types
      ) ==
      toset([
        "ReportBatchItemFailures",
      ])
    )
    error_message = "The processing event source must enable partial batch failure reporting."
  }

  assert {
    condition = (
      length(
        aws_lambda_event_source_mapping
        .processing_queue.scaling_config
      ) ==
      1
    )
    error_message = "The processing event source must define one scaling boundary."
  }

  assert {
    condition = (
      one(
        aws_lambda_event_source_mapping
        .processing_queue.scaling_config
      ).maximum_concurrency ==
      5
    )
    error_message = "The processing event source must limit concurrent Processor invocations to five."
  }

  assert {
    condition = (
      aws_lambda_function.processor
      .reserved_concurrent_executions ==
      null
    )
    error_message = "Reserved concurrency must remain unconfigured in this slice."
  }
}

run "processing_timeout_and_redrive_contract" {
  command = plan

  assert {
    condition = (
      aws_lambda_function.processor.timeout ==
      120
    )
    error_message = "The Document Processor timeout must remain 120 seconds."
  }

  assert {
    condition = (
      aws_sqs_queue.processing.visibility_timeout_seconds ==
      720
    )
    error_message = "The processing queue visibility timeout must remain 720 seconds."
  }

  assert {
    condition = (
      aws_sqs_queue.processing.visibility_timeout_seconds ==
      aws_lambda_function.processor.timeout * 6
    )
    error_message = "The processing queue visibility timeout must remain six times the Processor timeout."
  }

  assert {
    condition = (
      jsondecode(
        aws_sqs_queue_redrive_policy.processing.redrive_policy
      ).deadLetterTargetArn ==
      aws_sqs_queue.processing_dlq.arn
    )
    error_message = "Exhausted processing deliveries must still target the dedicated processing DLQ."
  }

  assert {
    condition = (
      jsondecode(
        aws_sqs_queue_redrive_policy.processing.redrive_policy
      ).maxReceiveCount ==
      3
    )
    error_message = "The processing queue must continue to redrive after three receives."
  }

  assert {
    condition = (
      aws_sqs_queue.processing.message_retention_seconds ==
      345600
    )
    error_message = "The processing queue must retain source messages for four days."
  }

  assert {
    condition = (
      aws_sqs_queue.processing_dlq.message_retention_seconds ==
      1209600
    )
    error_message = "The processing DLQ must retain exhausted messages for fourteen days."
  }

  assert {
    condition = (
      aws_sqs_queue.processing.sqs_managed_sse_enabled &&
      aws_sqs_queue.processing_dlq.sqs_managed_sse_enabled
    )
    error_message = "The processing queue and DLQ must continue to use SQS-managed encryption."
  }
}