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
  target          = aws_sqs_queue.reconciliation_failures
  override_during = plan

  values = {
    arn = "arn:aws:sqs:us-east-1:123456789012:clouddoc-dev-reconciliation-failures"
    url = "https://sqs.us-east-1.amazonaws.com/123456789012/clouddoc-dev-reconciliation-failures"
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

run "reconciliation_failure_quarantine_topology" {
  command = plan

  assert {
    condition = (
      local.reconciliation_failures_queue_name ==
      "clouddoc-dev-reconciliation-failures"
    )
    error_message = "The reconciliation failure queue name must be environment-scoped."
  }

  assert {
    condition = (
      aws_sqs_queue.reconciliation_failures.name ==
      local.reconciliation_failures_queue_name
    )
    error_message = "The quarantine queue must use the approved environment-scoped name."
  }

  assert {
    condition = (
      aws_sqs_queue.reconciliation_failures.fifo_queue ==
      false
    )
    error_message = "The reconciliation failure quarantine must be a Standard queue."
  }

  assert {
    condition = (
      aws_sqs_queue.reconciliation_failures.delay_seconds ==
      0
    )
    error_message = "The reconciliation failure queue must not delay new messages."
  }

  assert {
    condition = (
      aws_sqs_queue.reconciliation_failures
      .visibility_timeout_seconds ==
      180
    )
    error_message = "The reconciliation failure queue visibility timeout must be 180 seconds."
  }

  assert {
    condition = (
      aws_sqs_queue.reconciliation_failures
      .message_retention_seconds ==
      1209600
    )
    error_message = "The reconciliation failure queue must retain messages for fourteen days."
  }

  assert {
    condition = (
      aws_sqs_queue.reconciliation_failures
      .sqs_managed_sse_enabled
    )
    error_message = "The reconciliation failure queue must use SQS-managed encryption."
  }

  assert {
    condition = (
      aws_sqs_queue.reconciliation_failures.tags["Name"] ==
      local.reconciliation_failures_queue_name
    )
    error_message = "The quarantine queue Name tag must match its queue name."
  }

  assert {
    condition = (
      aws_sqs_queue.reconciliation_failures
      .tags["QueueRole"] ==
      "dead-letter-reconciliation-quarantine"
    )
    error_message = "The queue must be tagged as the dead-letter reconciliation quarantine."
  }

  assert {
    condition = (
      aws_sqs_queue_redrive_policy
      .processing_dlq_reconciliation.queue_url ==
      aws_sqs_queue.processing_dlq.url
    )
    error_message = "The reconciliation redrive policy must be attached to the processing DLQ."
  }

  assert {
    condition = (
      jsondecode(
        aws_sqs_queue_redrive_policy
        .processing_dlq_reconciliation.redrive_policy
      ).deadLetterTargetArn ==
      aws_sqs_queue.reconciliation_failures.arn
    )
    error_message = "Persistent reconciliation failures must target the quarantine queue."
  }

  assert {
    condition = (
      jsondecode(
        aws_sqs_queue_redrive_policy
        .processing_dlq_reconciliation.redrive_policy
      ).maxReceiveCount ==
      3
    )
    error_message = "The processing DLQ must quarantine messages after three reconciliation receives."
  }

  assert {
    condition = (
      aws_sqs_queue_redrive_allow_policy
      .reconciliation_failures.queue_url ==
      aws_sqs_queue.reconciliation_failures.url
    )
    error_message = "The quarantine redrive allow policy must be attached to the quarantine queue."
  }

  assert {
    condition = (
      jsondecode(
        aws_sqs_queue_redrive_allow_policy
        .reconciliation_failures.redrive_allow_policy
      ).redrivePermission ==
      "byQueue"
    )
    error_message = "The quarantine queue must restrict redrive access by source queue."
  }

  assert {
    condition = (
      jsondecode(
        aws_sqs_queue_redrive_allow_policy
        .reconciliation_failures.redrive_allow_policy
      ).sourceQueueArns ==
      [
        aws_sqs_queue.processing_dlq.arn,
      ]
    )
    error_message = "Only the processing DLQ may use the reconciliation failure quarantine."
  }

  assert {
    condition = (
      output.reconciliation_failures_queue_name ==
      aws_sqs_queue.reconciliation_failures.name &&
      output.reconciliation_failures_queue_arn ==
      aws_sqs_queue.reconciliation_failures.arn &&
      output.reconciliation_failures_queue_url ==
      aws_sqs_queue.reconciliation_failures.url
    )
    error_message = "Quarantine outputs must reference the reconciliation failure queue."
  }
}

run "dead_letter_reconciler_consumer_permissions" {
  command = plan

  assert {
    condition = (
      length(
        data.aws_iam_policy_document
        .dead_letter_reconciler_queue_consumer.statement
      ) ==
      1
    )
    error_message = "The reconciler queue-consumer policy must contain exactly one statement."
  }

  assert {
    condition = (
      one(
        data.aws_iam_policy_document
        .dead_letter_reconciler_queue_consumer.statement
      ).sid ==
      "ConsumeProcessingDeadLetterQueue"
    )
    error_message = "The reconciler queue permission must use the expected statement identifier."
  }

  assert {
    condition = (
      one(
        data.aws_iam_policy_document
        .dead_letter_reconciler_queue_consumer.statement
      ).effect ==
      "Allow"
    )
    error_message = "The reconciler queue-consumer statement must explicitly allow consumption."
  }

  assert {
    condition = (
      toset(
        one(
          data.aws_iam_policy_document
          .dead_letter_reconciler_queue_consumer.statement
        ).actions
      ) ==
      toset([
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:ReceiveMessage",
      ])
    )
    error_message = "The reconciler must receive exactly the required SQS consumer actions."
  }

  assert {
    condition = (
      toset(
        one(
          data.aws_iam_policy_document
          .dead_letter_reconciler_queue_consumer.statement
        ).resources
      ) ==
      toset([
        aws_sqs_queue.processing_dlq.arn,
      ])
    )
    error_message = "The reconciler SQS policy must target only the processing DLQ."
  }

  assert {
    condition = (
      aws_iam_role_policy
      .dead_letter_reconciler_queue_consumer.role ==
      aws_iam_role.dead_letter_reconciler.id
    )
    error_message = "The processing-DLQ consumer policy must be attached to the reconciler role."
  }

  assert {
    condition = (
      aws_iam_role_policy
      .dead_letter_reconciler_queue_consumer.name ==
      "${local.dead_letter_reconciler_function_name}-processing-dlq"
    )
    error_message = "The reconciler must use a dedicated processing-DLQ inline policy."
  }

  assert {
    condition = (
      !contains(
        one(
          data.aws_iam_policy_document
          .dead_letter_reconciler_queue_consumer.statement
        ).resources,
        aws_sqs_queue.processing.arn,
      ) &&
      !contains(
        one(
          data.aws_iam_policy_document
          .dead_letter_reconciler_queue_consumer.statement
        ).resources,
        aws_sqs_queue.reconciliation_failures.arn,
      ) &&
      !contains(
        one(
          data.aws_iam_policy_document
          .dead_letter_reconciler_queue_consumer.statement
        ).resources,
        "*",
      )
    )
    error_message = "The reconciler must not receive primary-queue, quarantine, or wildcard SQS access."
  }

  assert {
    condition = (
      length([
        for action in one(
          data.aws_iam_policy_document
          .dead_letter_reconciler_queue_consumer.statement
        ).actions : action
        if contains([
          "sqs:SendMessage",
          "sqs:ChangeMessageVisibility",
          "sqs:PurgeQueue",
          "sqs:SetQueueAttributes",
          "sqs:StartMessageMoveTask",
          "sqs:CancelMessageMoveTask",
          "sqs:ListMessageMoveTasks",
        ], action)
      ]) ==
      0
    )
    error_message = "The reconciler must not receive replay, publication, or queue-administration permissions."
  }
}

run "dead_letter_reconciliation_event_source" {
  command = plan

  assert {
    condition = (
      aws_lambda_event_source_mapping.processing_dlq
      .event_source_arn ==
      aws_sqs_queue.processing_dlq.arn
    )
    error_message = "The reconciliation event source must consume the processing DLQ."
  }

  assert {
    condition = (
      aws_lambda_event_source_mapping.processing_dlq
      .function_name ==
      aws_lambda_function.dead_letter_reconciler.arn
    )
    error_message = "The processing DLQ must target only the Dead-Letter Reconciler Lambda."
  }

  assert {
    condition = (
      aws_lambda_event_source_mapping.processing_dlq.enabled
    )
    error_message = "The processing-DLQ event source mapping must be enabled."
  }

  assert {
    condition = (
      aws_lambda_event_source_mapping.processing_dlq.batch_size ==
      1
    )
    error_message = "Each reconciliation invocation must receive at most one exhausted message."
  }

  assert {
    condition = (
      aws_lambda_event_source_mapping.processing_dlq
      .maximum_batching_window_in_seconds ==
      0
    )
    error_message = "The reconciliation mapping must not delay invocation to accumulate a batch."
  }

  assert {
    condition = (
      toset(
        aws_lambda_event_source_mapping
        .processing_dlq.function_response_types
      ) ==
      toset([
        "ReportBatchItemFailures",
      ])
    )
    error_message = "The reconciliation mapping must enable partial batch failure reporting."
  }

  assert {
    condition = (
      length(
        aws_lambda_event_source_mapping
        .processing_dlq.scaling_config
      ) ==
      1
    )
    error_message = "The reconciliation mapping must define one scaling boundary."
  }

  assert {
    condition = (
      one(
        aws_lambda_event_source_mapping
        .processing_dlq.scaling_config
      ).maximum_concurrency ==
      2
    )
    error_message = "The processing DLQ must invoke at most two reconciler instances concurrently."
  }

  assert {
    condition = (
      aws_lambda_function.dead_letter_reconciler
      .reserved_concurrent_executions ==
      null
    )
    error_message = "Reserved concurrency must remain unconfigured for the reconciler."
  }

  assert {
    condition = (
      aws_lambda_event_source_mapping.processing_queue
      .event_source_arn ==
      aws_sqs_queue.processing.arn &&
      aws_lambda_event_source_mapping.processing_queue
      .function_name ==
      aws_lambda_function.processor.arn
    )
    error_message = "The primary processing event-source mapping must remain unchanged."
  }
}

run "dead_letter_reconciliation_retry_contract" {
  command = plan

  assert {
    condition = (
      aws_lambda_function.dead_letter_reconciler.timeout ==
      30
    )
    error_message = "The Dead-Letter Reconciler timeout must remain 30 seconds."
  }

  assert {
    condition = (
      aws_sqs_queue.processing_dlq.visibility_timeout_seconds ==
      180
    )
    error_message = "The processing DLQ visibility timeout must remain 180 seconds."
  }

  assert {
    condition = (
      aws_sqs_queue.processing_dlq.visibility_timeout_seconds ==
      aws_lambda_function.dead_letter_reconciler.timeout * 6
    )
    error_message = "The processing DLQ visibility timeout must remain six times the reconciler timeout."
  }

  assert {
    condition = (
      jsondecode(
        aws_sqs_queue_redrive_policy
        .processing_dlq_reconciliation.redrive_policy
      ).maxReceiveCount ==
      3
    )
    error_message = "Persistent reconciliation failures must be quarantined after three receives."
  }

  assert {
    condition = (
      jsondecode(
        aws_sqs_queue_redrive_policy
        .processing_dlq_reconciliation.redrive_policy
      ).deadLetterTargetArn ==
      aws_sqs_queue.reconciliation_failures.arn
    )
    error_message = "Exhausted reconciliation failures must target the terminal quarantine queue."
  }

  assert {
    condition = (
      aws_sqs_queue.processing_dlq.message_retention_seconds ==
      1209600 &&
      aws_sqs_queue.reconciliation_failures
      .message_retention_seconds ==
      1209600
    )
    error_message = "The processing DLQ and quarantine queue must each retain messages for fourteen days."
  }

  assert {
    condition = (
      aws_sqs_queue.processing_dlq.sqs_managed_sse_enabled &&
      aws_sqs_queue.reconciliation_failures
      .sqs_managed_sse_enabled
    )
    error_message = "The processing DLQ and quarantine queue must use SQS-managed encryption."
  }
}