mock_provider "aws" {
  override_during = plan

  # IAM policy resources require valid rendered JSON during mocked plans.
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

override_data {
  target          = data.aws_partition.current
  override_during = plan

  values = {
    partition = "aws"
  }
}

override_resource {
  target          = aws_s3_bucket.documents
  override_during = plan

  values = {
    id     = "clouddoc-dev-123456789012-documents"
    bucket = "clouddoc-dev-123456789012-documents"
    arn    = "arn:aws:s3:::clouddoc-dev-123456789012-documents"
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
    name = "clouddoc-dev-processing"
    arn  = "arn:aws:sqs:us-east-1:123456789012:clouddoc-dev-processing"
    url  = "https://sqs.us-east-1.amazonaws.com/123456789012/clouddoc-dev-processing"
  }
}

override_resource {
  target          = aws_sqs_queue.processing_dlq
  override_during = plan

  values = {
    name = "clouddoc-dev-processing-dlq"
    arn  = "arn:aws:sqs:us-east-1:123456789012:clouddoc-dev-processing-dlq"
    url  = "https://sqs.us-east-1.amazonaws.com/123456789012/clouddoc-dev-processing-dlq"
  }
}

override_resource {
  target          = aws_sqs_queue.reconciliation_failures
  override_during = plan

  values = {
    name = "clouddoc-dev-reconciliation-failures"
    arn  = "arn:aws:sqs:us-east-1:123456789012:clouddoc-dev-reconciliation-failures"
    url  = "https://sqs.us-east-1.amazonaws.com/123456789012/clouddoc-dev-reconciliation-failures"
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
    invoke_arn    = "arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-create-job/invocations"
  }
}

override_resource {
  target          = aws_lambda_function.get_job
  override_during = plan

  values = {
    function_name = "clouddoc-dev-get-job"
    arn           = "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-get-job"
    invoke_arn    = "arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-get-job/invocations"
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

override_resource {
  target          = aws_apigatewayv2_api.control_plane
  override_during = plan

  values = {
    id            = "api-observability-test"
    api_endpoint  = "https://api-observability-test.execute-api.us-east-1.amazonaws.com"
    execution_arn = "arn:aws:execute-api:us-east-1:123456789012:api-observability-test"
  }
}

override_resource {
  target          = aws_apigatewayv2_stage.control_plane
  override_during = plan

  values = {
    id   = "dev"
    name = "dev"
  }
}

override_resource {
  target          = aws_cloudwatch_metric_alarm.control_plane_5xx
  override_during = plan

  values = {
    arn = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:clouddoc-dev-control-plane-5xx"
  }
}

override_resource {
  target          = aws_cloudwatch_metric_alarm.processor_lambda_errors
  override_during = plan

  values = {
    arn = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:clouddoc-dev-processor-lambda-errors"
  }
}

override_resource {
  target          = aws_cloudwatch_metric_alarm.dead_letter_reconciler_lambda_errors
  override_during = plan

  values = {
    arn = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:clouddoc-dev-reconciler-lambda-errors"
  }
}

override_resource {
  target          = aws_cloudwatch_metric_alarm.processing_queue_age
  override_during = plan

  values = {
    arn = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:clouddoc-dev-processing-queue-age"
  }
}

override_resource {
  target          = aws_cloudwatch_metric_alarm.processing_dlq_visible
  override_during = plan

  values = {
    arn = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:clouddoc-dev-processing-dlq-visible"
  }
}

override_resource {
  target          = aws_cloudwatch_metric_alarm.reconciliation_quarantine_visible
  override_during = plan

  values = {
    arn = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:clouddoc-dev-reconciliation-quarantine-visible"
  }
}

override_resource {
  target          = aws_cloudwatch_metric_alarm.bedrock_client_errors
  override_during = plan

  values = {
    arn = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:clouddoc-dev-bedrock-client-errors"
  }
}

override_resource {
  target          = aws_cloudwatch_metric_alarm.bedrock_server_errors
  override_during = plan

  values = {
    arn = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:clouddoc-dev-bedrock-server-errors"
  }
}

override_resource {
  target          = aws_cloudwatch_metric_alarm.bedrock_throttles
  override_during = plan

  values = {
    arn = "arn:aws:cloudwatch:us-east-1:123456789012:alarm:clouddoc-dev-bedrock-throttles"
  }
}

run "cloudwatch_alarm_contracts" {
  command = plan

  assert {
    condition = (
      toset([
        aws_cloudwatch_metric_alarm.control_plane_5xx.alarm_name,
        aws_cloudwatch_metric_alarm.processor_lambda_errors.alarm_name,
        aws_cloudwatch_metric_alarm.dead_letter_reconciler_lambda_errors.alarm_name,
        aws_cloudwatch_metric_alarm.processing_queue_age.alarm_name,
        aws_cloudwatch_metric_alarm.processing_dlq_visible.alarm_name,
        aws_cloudwatch_metric_alarm.reconciliation_quarantine_visible.alarm_name,
        aws_cloudwatch_metric_alarm.bedrock_client_errors.alarm_name,
        aws_cloudwatch_metric_alarm.bedrock_server_errors.alarm_name,
        aws_cloudwatch_metric_alarm.bedrock_throttles.alarm_name,
        ]) == toset([
        "clouddoc-dev-control-plane-5xx",
        "clouddoc-dev-processor-lambda-errors",
        "clouddoc-dev-reconciler-lambda-errors",
        "clouddoc-dev-processing-queue-age",
        "clouddoc-dev-processing-dlq-visible",
        "clouddoc-dev-reconciliation-quarantine-visible",
        "clouddoc-dev-bedrock-client-errors",
        "clouddoc-dev-bedrock-server-errors",
        "clouddoc-dev-bedrock-throttles",
      ])
    )
    error_message = "The observability slice must declare exactly the nine approved environment-scoped alarms."
  }

  assert {
    condition = alltrue([
      for alarm in [
        aws_cloudwatch_metric_alarm.control_plane_5xx,
        aws_cloudwatch_metric_alarm.processor_lambda_errors,
        aws_cloudwatch_metric_alarm.dead_letter_reconciler_lambda_errors,
        aws_cloudwatch_metric_alarm.processing_queue_age,
        aws_cloudwatch_metric_alarm.processing_dlq_visible,
        aws_cloudwatch_metric_alarm.reconciliation_quarantine_visible,
        aws_cloudwatch_metric_alarm.bedrock_client_errors,
        aws_cloudwatch_metric_alarm.bedrock_server_errors,
        aws_cloudwatch_metric_alarm.bedrock_throttles,
        ] : (
        alarm.comparison_operator == "GreaterThanOrEqualToThreshold" &&
        alarm.treat_missing_data == "notBreaching"
      )
    ])
    error_message = "Every operational alarm must use an explicit threshold comparison and treat absent metrics as non-breaching."
  }

  assert {
    condition = (
      aws_cloudwatch_metric_alarm.control_plane_5xx.namespace ==
      "AWS/ApiGateway" &&
      aws_cloudwatch_metric_alarm.control_plane_5xx.metric_name == "5xx" &&
      aws_cloudwatch_metric_alarm.control_plane_5xx.dimensions == tomap({
        ApiId = aws_apigatewayv2_api.control_plane.id
        Stage = aws_apigatewayv2_stage.control_plane.name
      }) &&
      aws_cloudwatch_metric_alarm.control_plane_5xx.statistic == "Sum" &&
      aws_cloudwatch_metric_alarm.control_plane_5xx.threshold == 1 &&
      aws_cloudwatch_metric_alarm.control_plane_5xx.period == 300 &&
      aws_cloudwatch_metric_alarm.control_plane_5xx.evaluation_periods == 1 &&
      aws_cloudwatch_metric_alarm.control_plane_5xx.datapoints_to_alarm == 1
    )
    error_message = "The control-plane alarm must detect any five-minute API Gateway 5xx signal at the API and stage boundary."
  }

  assert {
    condition = alltrue([
      for alarm in [
        {
          actual        = aws_cloudwatch_metric_alarm.processor_lambda_errors
          function_name = aws_lambda_function.processor.function_name
        },
        {
          actual        = aws_cloudwatch_metric_alarm.dead_letter_reconciler_lambda_errors
          function_name = aws_lambda_function.dead_letter_reconciler.function_name
        },
        ] : (
        alarm.actual.namespace == "AWS/Lambda" &&
        alarm.actual.metric_name == "Errors" &&
        alarm.actual.dimensions == tomap({
          FunctionName = alarm.function_name
        }) &&
        alarm.actual.statistic == "Sum" &&
        alarm.actual.threshold == 1 &&
        alarm.actual.period == 300 &&
        alarm.actual.evaluation_periods == 1 &&
        alarm.actual.datapoints_to_alarm == 1
      )
    ])
    error_message = "Processor and reconciler runtime alarms must detect any five-minute Lambda error signal against their exact functions."
  }

  assert {
    condition = (
      aws_cloudwatch_metric_alarm.processing_queue_age.namespace == "AWS/SQS" &&
      aws_cloudwatch_metric_alarm.processing_queue_age.metric_name ==
      "ApproximateAgeOfOldestMessage" &&
      aws_cloudwatch_metric_alarm.processing_queue_age.dimensions == tomap({
        QueueName = aws_sqs_queue.processing.name
      }) &&
      aws_cloudwatch_metric_alarm.processing_queue_age.statistic == "Maximum" &&
      aws_cloudwatch_metric_alarm.processing_queue_age.threshold == 300 &&
      aws_cloudwatch_metric_alarm.processing_queue_age.period == 60 &&
      aws_cloudwatch_metric_alarm.processing_queue_age.evaluation_periods == 3 &&
      aws_cloudwatch_metric_alarm.processing_queue_age.datapoints_to_alarm == 2
    )
    error_message = "The processing backlog alarm must require an oldest-message age of five minutes in two of three one-minute periods."
  }

  assert {
    condition = alltrue([
      for alarm in [
        {
          actual     = aws_cloudwatch_metric_alarm.processing_dlq_visible
          queue_name = aws_sqs_queue.processing_dlq.name
        },
        {
          actual     = aws_cloudwatch_metric_alarm.reconciliation_quarantine_visible
          queue_name = aws_sqs_queue.reconciliation_failures.name
        },
        ] : (
        alarm.actual.namespace == "AWS/SQS" &&
        alarm.actual.metric_name == "ApproximateNumberOfMessagesVisible" &&
        alarm.actual.dimensions == tomap({
          QueueName = alarm.queue_name
        }) &&
        alarm.actual.statistic == "Maximum" &&
        alarm.actual.threshold == 1 &&
        alarm.actual.period == 60 &&
        alarm.actual.evaluation_periods == 1 &&
        alarm.actual.datapoints_to_alarm == 1
      )
    ])
    error_message = "DLQ and quarantine alarms must detect any visible terminal message against the exact queues."
  }

  assert {
    condition = alltrue([
      for alarm in [
        {
          actual      = aws_cloudwatch_metric_alarm.bedrock_client_errors
          metric_name = "InvocationClientErrors"
        },
        {
          actual      = aws_cloudwatch_metric_alarm.bedrock_server_errors
          metric_name = "InvocationServerErrors"
        },
        {
          actual      = aws_cloudwatch_metric_alarm.bedrock_throttles
          metric_name = "InvocationThrottles"
        },
        ] : (
        alarm.actual.namespace == "AWS/Bedrock" &&
        alarm.actual.metric_name == alarm.metric_name &&
        alarm.actual.dimensions == tomap({
          ModelId = local.bedrock_model_id
        }) &&
        alarm.actual.statistic == "Sum" &&
        alarm.actual.threshold == 1 &&
        alarm.actual.period == 300 &&
        alarm.actual.evaluation_periods == 1 &&
        alarm.actual.datapoints_to_alarm == 1
      )
    ])
    error_message = "Bedrock alarms must monitor the approved model's client errors, server errors, and throttles."
  }
}

run "operations_dashboard_contract" {
  command = plan

  assert {
    condition = (
      local.operations_dashboard_name == "clouddoc-dev-operations" &&
      aws_cloudwatch_dashboard.operations.dashboard_name ==
      local.operations_dashboard_name &&
      output.operations_dashboard_name ==
      aws_cloudwatch_dashboard.operations.dashboard_name
    )
    error_message = "The operations dashboard and Terraform output must use the canonical environment-scoped name."
  }

  assert {
    condition = (
      jsondecode(
        aws_cloudwatch_dashboard.operations.dashboard_body
      ).start == "-PT6H" &&
      jsondecode(
        aws_cloudwatch_dashboard.operations.dashboard_body
      ).periodOverride == "inherit" &&
      length(
        jsondecode(
          aws_cloudwatch_dashboard.operations.dashboard_body
        ).widgets
      ) == 10
    )
    error_message = "The dashboard must expose the approved six-hour operational view with exactly ten widgets."
  }

  assert {
    condition = (
      jsondecode(
        aws_cloudwatch_dashboard.operations.dashboard_body
      ).widgets[0].type == "alarm" &&
      jsondecode(
        aws_cloudwatch_dashboard.operations.dashboard_body
      ).widgets[0].properties.title == "Operational alarm status" &&
      length(
        jsondecode(
          aws_cloudwatch_dashboard.operations.dashboard_body
        ).widgets[0].properties.alarms
      ) == 9
    )
    error_message = "The first dashboard widget must summarize all nine operational alarm states."
  }

  assert {
    condition = (
      toset([
        for widget in slice(
          jsondecode(
            aws_cloudwatch_dashboard.operations.dashboard_body
          ).widgets,
          1,
          10,
        ) : widget.properties.title
        ]) == toset([
        "Control plane traffic and errors",
        "Control plane latency",
        "Lambda errors and throttles",
        "Lambda duration and concurrency",
        "Processing queue health",
        "Dead-letter and quarantine health",
        "Amazon Bedrock invocations and errors",
        "Amazon Bedrock invocation latency",
        "Amazon Bedrock token usage",
      ])
    )
    error_message = "The dashboard must contain the nine approved metric views without unrelated operational panels."
  }

  assert {
    condition = alltrue([
      for widget in slice(
        jsondecode(
          aws_cloudwatch_dashboard.operations.dashboard_body
        ).widgets,
        1,
        10,
        ) : (
        widget.type == "metric" &&
        widget.properties.region == var.aws_region
      )
    ])
    error_message = "Every metric widget must use the deployment Region and the native CloudWatch metric widget type."
  }
}

run "lambda_structured_logging_contract" {
  command = plan

  assert {
    condition = alltrue([
      for function in [
        aws_lambda_function.create_job,
        aws_lambda_function.get_job,
        aws_lambda_function.processor,
        aws_lambda_function.dead_letter_reconciler,
        ] : (
        one(function.logging_config).log_format == "JSON" &&
        one(function.logging_config).application_log_level == "INFO" &&
        one(function.logging_config).system_log_level == "WARN"
      )
    ])
    error_message = "Every Lambda must preserve JSON application events at INFO and restrict platform logs below WARN."
  }
}

run "observability_isolation_boundaries" {
  command = plan

  assert {
    condition = alltrue([
      for alarm in [
        aws_cloudwatch_metric_alarm.control_plane_5xx,
        aws_cloudwatch_metric_alarm.processor_lambda_errors,
        aws_cloudwatch_metric_alarm.dead_letter_reconciler_lambda_errors,
        aws_cloudwatch_metric_alarm.processing_queue_age,
        aws_cloudwatch_metric_alarm.processing_dlq_visible,
        aws_cloudwatch_metric_alarm.reconciliation_quarantine_visible,
        aws_cloudwatch_metric_alarm.bedrock_client_errors,
        aws_cloudwatch_metric_alarm.bedrock_server_errors,
        aws_cloudwatch_metric_alarm.bedrock_throttles,
        ] : (
        length(coalesce(alarm.alarm_actions, [])) == 0 &&
        length(coalesce(alarm.ok_actions, [])) == 0 &&
        length(coalesce(alarm.insufficient_data_actions, [])) == 0
      )
    ])
    error_message = "Operational alarms must remain free of notification actions until an approved incident-routing boundary exists."
  }

  assert {
    condition = alltrue([
      for alarm in [
        aws_cloudwatch_metric_alarm.control_plane_5xx,
        aws_cloudwatch_metric_alarm.processor_lambda_errors,
        aws_cloudwatch_metric_alarm.dead_letter_reconciler_lambda_errors,
        aws_cloudwatch_metric_alarm.processing_queue_age,
        aws_cloudwatch_metric_alarm.processing_dlq_visible,
        aws_cloudwatch_metric_alarm.reconciliation_quarantine_visible,
        aws_cloudwatch_metric_alarm.bedrock_client_errors,
        aws_cloudwatch_metric_alarm.bedrock_server_errors,
        aws_cloudwatch_metric_alarm.bedrock_throttles,
      ] : startswith(alarm.namespace, "AWS/")
    ])
    error_message = "Every alarm must use an AWS-native metric namespace rather than an application-owned custom namespace."
  }

  assert {
    condition = alltrue([
      for forbidden_value in [
        "job_id",
        "request_id",
        "correlation_id",
        "processing_attempt_id",
        "provider_request_id",
        "document_text",
        "raw_model_response",
        "CloudDoc/",
        ] : (
        length(
          regexall(
            forbidden_value,
            aws_cloudwatch_dashboard.operations.dashboard_body,
          )
        ) == 0
      )
    ])
    error_message = "The dashboard must contain no high-cardinality identifiers, document fields, raw model fields, or custom metric namespace."
  }

  assert {
    condition = (
      length([
        for action in flatten([
          flatten([
            for statement in data.aws_iam_policy_document.create_job_logging.statement :
            statement.actions
          ]),
          flatten([
            for statement in data.aws_iam_policy_document.get_job_logging.statement :
            statement.actions
          ]),
          flatten([
            for statement in data.aws_iam_policy_document.processor_logging.statement :
            statement.actions
          ]),
          flatten([
            for statement in data.aws_iam_policy_document.dead_letter_reconciler_logging.statement :
            statement.actions
          ]),
          flatten([
            for statement in data.aws_iam_policy_document.create_job_permissions.statement :
            statement.actions
          ]),
          flatten([
            for statement in data.aws_iam_policy_document.get_job_permissions.statement :
            statement.actions
          ]),
          flatten([
            for statement in data.aws_iam_policy_document.processor_permissions.statement :
            statement.actions
          ]),
          flatten([
            for statement in data.aws_iam_policy_document.processor_queue_consumer.statement :
            statement.actions
          ]),
          flatten([
            for statement in data.aws_iam_policy_document.dead_letter_reconciler_permissions.statement :
            statement.actions
          ]),
          flatten([
            for statement in data.aws_iam_policy_document.dead_letter_reconciler_queue_consumer.statement :
            statement.actions
          ]),
          flatten([
            for statement in data.aws_iam_policy_document.processor_bedrock_invoke.statement :
            statement.actions
          ]),
        ]) : action
        if action == "cloudwatch:PutMetricData" || action == "cloudwatch:*"
      ]) == 0
    )
    error_message = "Lambda execution policies must not gain custom CloudWatch metric permissions."
  }
}
