locals {
  operations_dashboard_name = "${local.name_prefix}-operations"
}

resource "aws_cloudwatch_metric_alarm" "control_plane_5xx" {
  alarm_name        = "${local.name_prefix}-control-plane-5xx"
  alarm_description = "Detects server-side failures returned by the CloudDoc HTTP control plane."

  namespace   = "AWS/ApiGateway"
  metric_name = "5xx"
  dimensions = {
    ApiId = aws_apigatewayv2_api.control_plane.id
    Stage = aws_apigatewayv2_stage.control_plane.name
  }

  comparison_operator = "GreaterThanOrEqualToThreshold"
  statistic           = "Sum"
  threshold           = 1
  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  treat_missing_data  = "notBreaching"

  tags = {
    Name      = "${local.name_prefix}-control-plane-5xx"
    AlarmRole = "control-plane-server-errors"
  }
}

resource "aws_cloudwatch_metric_alarm" "processor_lambda_errors" {
  alarm_name        = "${local.name_prefix}-processor-lambda-errors"
  alarm_description = "Detects invocation errors in the asynchronous Document Processor Lambda."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"
  dimensions = {
    FunctionName = aws_lambda_function.processor.function_name
  }

  comparison_operator = "GreaterThanOrEqualToThreshold"
  statistic           = "Sum"
  threshold           = 1
  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  treat_missing_data  = "notBreaching"

  tags = {
    Name      = "${local.name_prefix}-processor-lambda-errors"
    AlarmRole = "processor-runtime-errors"
  }
}

resource "aws_cloudwatch_metric_alarm" "dead_letter_reconciler_lambda_errors" {
  alarm_name        = "${local.name_prefix}-reconciler-lambda-errors"
  alarm_description = "Detects invocation errors in the Dead-Letter Reconciler Lambda."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"
  dimensions = {
    FunctionName = aws_lambda_function.dead_letter_reconciler.function_name
  }

  comparison_operator = "GreaterThanOrEqualToThreshold"
  statistic           = "Sum"
  threshold           = 1
  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  treat_missing_data  = "notBreaching"

  tags = {
    Name      = "${local.name_prefix}-reconciler-lambda-errors"
    AlarmRole = "reconciler-runtime-errors"
  }
}

resource "aws_cloudwatch_metric_alarm" "processing_queue_age" {
  alarm_name        = "${local.name_prefix}-processing-queue-age"
  alarm_description = "Detects sustained processing backlog older than five minutes."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateAgeOfOldestMessage"
  dimensions = {
    QueueName = aws_sqs_queue.processing.name
  }

  comparison_operator = "GreaterThanOrEqualToThreshold"
  statistic           = "Maximum"
  threshold           = 300
  period              = 60
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  treat_missing_data  = "notBreaching"

  tags = {
    Name      = "${local.name_prefix}-processing-queue-age"
    AlarmRole = "processing-backlog"
  }
}

resource "aws_cloudwatch_metric_alarm" "processing_dlq_visible" {
  alarm_name        = "${local.name_prefix}-processing-dlq-visible"
  alarm_description = "Detects documents that exhausted processing retries and entered the processing DLQ."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"
  dimensions = {
    QueueName = aws_sqs_queue.processing_dlq.name
  }

  comparison_operator = "GreaterThanOrEqualToThreshold"
  statistic           = "Maximum"
  threshold           = 1
  period              = 60
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  treat_missing_data  = "notBreaching"

  tags = {
    Name      = "${local.name_prefix}-processing-dlq-visible"
    AlarmRole = "processing-dead-letter"
  }
}

resource "aws_cloudwatch_metric_alarm" "reconciliation_quarantine_visible" {
  alarm_name        = "${local.name_prefix}-reconciliation-quarantine-visible"
  alarm_description = "Detects reconciliation messages that exhausted retries and entered terminal quarantine."

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"
  dimensions = {
    QueueName = aws_sqs_queue.reconciliation_failures.name
  }

  comparison_operator = "GreaterThanOrEqualToThreshold"
  statistic           = "Maximum"
  threshold           = 1
  period              = 60
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  treat_missing_data  = "notBreaching"

  tags = {
    Name      = "${local.name_prefix}-reconciliation-quarantine-visible"
    AlarmRole = "reconciliation-quarantine"
  }
}

resource "aws_cloudwatch_metric_alarm" "bedrock_client_errors" {
  alarm_name        = "${local.name_prefix}-bedrock-client-errors"
  alarm_description = "Detects Amazon Bedrock invocation failures caused by client-side requests, authorization, or configuration."

  namespace   = "AWS/Bedrock"
  metric_name = "InvocationClientErrors"
  dimensions = {
    ModelId = local.bedrock_model_id
  }

  comparison_operator = "GreaterThanOrEqualToThreshold"
  statistic           = "Sum"
  threshold           = 1
  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  treat_missing_data  = "notBreaching"

  tags = {
    Name      = "${local.name_prefix}-bedrock-client-errors"
    AlarmRole = "bedrock-client-errors"
  }
}

resource "aws_cloudwatch_metric_alarm" "bedrock_server_errors" {
  alarm_name        = "${local.name_prefix}-bedrock-server-errors"
  alarm_description = "Detects Amazon Bedrock invocation failures caused by service-side errors."

  namespace   = "AWS/Bedrock"
  metric_name = "InvocationServerErrors"
  dimensions = {
    ModelId = local.bedrock_model_id
  }

  comparison_operator = "GreaterThanOrEqualToThreshold"
  statistic           = "Sum"
  threshold           = 1
  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  treat_missing_data  = "notBreaching"

  tags = {
    Name      = "${local.name_prefix}-bedrock-server-errors"
    AlarmRole = "bedrock-server-errors"
  }
}

resource "aws_cloudwatch_metric_alarm" "bedrock_throttles" {
  alarm_name        = "${local.name_prefix}-bedrock-throttles"
  alarm_description = "Detects throttled Amazon Bedrock model invocations."

  namespace   = "AWS/Bedrock"
  metric_name = "InvocationThrottles"
  dimensions = {
    ModelId = local.bedrock_model_id
  }

  comparison_operator = "GreaterThanOrEqualToThreshold"
  statistic           = "Sum"
  threshold           = 1
  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  treat_missing_data  = "notBreaching"

  tags = {
    Name      = "${local.name_prefix}-bedrock-throttles"
    AlarmRole = "bedrock-throttling"
  }
}

resource "aws_cloudwatch_dashboard" "operations" {
  dashboard_name = local.operations_dashboard_name

  dashboard_body = jsonencode({
    start          = "-PT6H"
    periodOverride = "inherit"

    widgets = [
      {
        type   = "alarm"
        x      = 0
        y      = 0
        width  = 24
        height = 5

        properties = {
          title  = "Operational alarm status"
          sortBy = "stateUpdatedTimestamp"
          alarms = [
            aws_cloudwatch_metric_alarm.control_plane_5xx.arn,
            aws_cloudwatch_metric_alarm.processor_lambda_errors.arn,
            aws_cloudwatch_metric_alarm.dead_letter_reconciler_lambda_errors.arn,
            aws_cloudwatch_metric_alarm.processing_queue_age.arn,
            aws_cloudwatch_metric_alarm.processing_dlq_visible.arn,
            aws_cloudwatch_metric_alarm.reconciliation_quarantine_visible.arn,
            aws_cloudwatch_metric_alarm.bedrock_client_errors.arn,
            aws_cloudwatch_metric_alarm.bedrock_server_errors.arn,
            aws_cloudwatch_metric_alarm.bedrock_throttles.arn,
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 5
        width  = 12
        height = 6

        properties = {
          title   = "Control plane traffic and errors"
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          period  = 300
          metrics = [
            [
              "AWS/ApiGateway",
              "Count",
              "ApiId",
              aws_apigatewayv2_api.control_plane.id,
              "Stage",
              aws_apigatewayv2_stage.control_plane.name,
              {
                label = "Requests"
                stat  = "Sum"
              },
            ],
            [
              "AWS/ApiGateway",
              "4xx",
              "ApiId",
              aws_apigatewayv2_api.control_plane.id,
              "Stage",
              aws_apigatewayv2_stage.control_plane.name,
              {
                label = "4xx"
                stat  = "Sum"
              },
            ],
            [
              "AWS/ApiGateway",
              "5xx",
              "ApiId",
              aws_apigatewayv2_api.control_plane.id,
              "Stage",
              aws_apigatewayv2_stage.control_plane.name,
              {
                label = "5xx"
                stat  = "Sum"
              },
            ],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 5
        width  = 12
        height = 6

        properties = {
          title   = "Control plane latency"
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          period  = 300
          metrics = [
            [
              "AWS/ApiGateway",
              "Latency",
              "ApiId",
              aws_apigatewayv2_api.control_plane.id,
              "Stage",
              aws_apigatewayv2_stage.control_plane.name,
              {
                label = "Latency p95"
                stat  = "p95"
              },
            ],
            [
              "AWS/ApiGateway",
              "IntegrationLatency",
              "ApiId",
              aws_apigatewayv2_api.control_plane.id,
              "Stage",
              aws_apigatewayv2_stage.control_plane.name,
              {
                label = "Integration latency p95"
                stat  = "p95"
              },
            ],
          ]
          yAxis = {
            left = {
              label     = "Milliseconds"
              showUnits = false
            }
          }
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 11
        width  = 12
        height = 6

        properties = {
          title   = "Lambda errors and throttles"
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          period  = 300
          metrics = [
            [
              "AWS/Lambda",
              "Errors",
              "FunctionName",
              aws_lambda_function.create_job.function_name,
              {
                label = "Create Job errors"
                stat  = "Sum"
              },
            ],
            [
              "AWS/Lambda",
              "Throttles",
              "FunctionName",
              aws_lambda_function.create_job.function_name,
              {
                label = "Create Job throttles"
                stat  = "Sum"
              },
            ],
            [
              "AWS/Lambda",
              "Errors",
              "FunctionName",
              aws_lambda_function.get_job.function_name,
              {
                label = "Get Job errors"
                stat  = "Sum"
              },
            ],
            [
              "AWS/Lambda",
              "Throttles",
              "FunctionName",
              aws_lambda_function.get_job.function_name,
              {
                label = "Get Job throttles"
                stat  = "Sum"
              },
            ],
            [
              "AWS/Lambda",
              "Errors",
              "FunctionName",
              aws_lambda_function.processor.function_name,
              {
                label = "Processor errors"
                stat  = "Sum"
              },
            ],
            [
              "AWS/Lambda",
              "Throttles",
              "FunctionName",
              aws_lambda_function.processor.function_name,
              {
                label = "Processor throttles"
                stat  = "Sum"
              },
            ],
            [
              "AWS/Lambda",
              "Errors",
              "FunctionName",
              aws_lambda_function.dead_letter_reconciler.function_name,
              {
                label = "Reconciler errors"
                stat  = "Sum"
              },
            ],
            [
              "AWS/Lambda",
              "Throttles",
              "FunctionName",
              aws_lambda_function.dead_letter_reconciler.function_name,
              {
                label = "Reconciler throttles"
                stat  = "Sum"
              },
            ],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 11
        width  = 12
        height = 6

        properties = {
          title   = "Lambda duration and concurrency"
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          period  = 300
          metrics = [
            [
              "AWS/Lambda",
              "Duration",
              "FunctionName",
              aws_lambda_function.create_job.function_name,
              {
                label = "Create Job duration p95"
                stat  = "p95"
              },
            ],
            [
              "AWS/Lambda",
              "ConcurrentExecutions",
              "FunctionName",
              aws_lambda_function.create_job.function_name,
              {
                label = "Create Job concurrency"
                stat  = "Maximum"
                yAxis = "right"
              },
            ],
            [
              "AWS/Lambda",
              "Duration",
              "FunctionName",
              aws_lambda_function.get_job.function_name,
              {
                label = "Get Job duration p95"
                stat  = "p95"
              },
            ],
            [
              "AWS/Lambda",
              "ConcurrentExecutions",
              "FunctionName",
              aws_lambda_function.get_job.function_name,
              {
                label = "Get Job concurrency"
                stat  = "Maximum"
                yAxis = "right"
              },
            ],
            [
              "AWS/Lambda",
              "Duration",
              "FunctionName",
              aws_lambda_function.processor.function_name,
              {
                label = "Processor duration p95"
                stat  = "p95"
              },
            ],
            [
              "AWS/Lambda",
              "ConcurrentExecutions",
              "FunctionName",
              aws_lambda_function.processor.function_name,
              {
                label = "Processor concurrency"
                stat  = "Maximum"
                yAxis = "right"
              },
            ],
            [
              "AWS/Lambda",
              "Duration",
              "FunctionName",
              aws_lambda_function.dead_letter_reconciler.function_name,
              {
                label = "Reconciler duration p95"
                stat  = "p95"
              },
            ],
            [
              "AWS/Lambda",
              "ConcurrentExecutions",
              "FunctionName",
              aws_lambda_function.dead_letter_reconciler.function_name,
              {
                label = "Reconciler concurrency"
                stat  = "Maximum"
                yAxis = "right"
              },
            ],
          ]
          yAxis = {
            left = {
              label     = "Milliseconds"
              showUnits = false
            }
            right = {
              label     = "Concurrent executions"
              showUnits = false
            }
          }
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 17
        width  = 12
        height = 6

        properties = {
          title   = "Processing queue health"
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          period  = 60
          metrics = [
            [
              "AWS/SQS",
              "ApproximateNumberOfMessagesVisible",
              "QueueName",
              aws_sqs_queue.processing.name,
              {
                label = "Visible"
                stat  = "Maximum"
              },
            ],
            [
              "AWS/SQS",
              "ApproximateNumberOfMessagesNotVisible",
              "QueueName",
              aws_sqs_queue.processing.name,
              {
                label = "In flight"
                stat  = "Maximum"
              },
            ],
            [
              "AWS/SQS",
              "ApproximateAgeOfOldestMessage",
              "QueueName",
              aws_sqs_queue.processing.name,
              {
                label = "Oldest message age"
                stat  = "Maximum"
                yAxis = "right"
              },
            ],
          ]
          yAxis = {
            left = {
              label     = "Messages"
              showUnits = false
            }
            right = {
              label     = "Seconds"
              showUnits = false
            }
          }
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 17
        width  = 12
        height = 6

        properties = {
          title   = "Dead-letter and quarantine health"
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          period  = 60
          metrics = [
            [
              "AWS/SQS",
              "ApproximateNumberOfMessagesVisible",
              "QueueName",
              aws_sqs_queue.processing_dlq.name,
              {
                label = "Processing DLQ visible"
                stat  = "Maximum"
              },
            ],
            [
              "AWS/SQS",
              "ApproximateAgeOfOldestMessage",
              "QueueName",
              aws_sqs_queue.processing_dlq.name,
              {
                label = "Processing DLQ oldest age"
                stat  = "Maximum"
                yAxis = "right"
              },
            ],
            [
              "AWS/SQS",
              "ApproximateNumberOfMessagesVisible",
              "QueueName",
              aws_sqs_queue.reconciliation_failures.name,
              {
                label = "Quarantine visible"
                stat  = "Maximum"
              },
            ],
            [
              "AWS/SQS",
              "ApproximateAgeOfOldestMessage",
              "QueueName",
              aws_sqs_queue.reconciliation_failures.name,
              {
                label = "Quarantine oldest age"
                stat  = "Maximum"
                yAxis = "right"
              },
            ],
          ]
          yAxis = {
            left = {
              label     = "Messages"
              showUnits = false
            }
            right = {
              label     = "Seconds"
              showUnits = false
            }
          }
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 23
        width  = 12
        height = 6

        properties = {
          title   = "Amazon Bedrock invocations and errors"
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          period  = 300
          metrics = [
            [
              "AWS/Bedrock",
              "Invocations",
              "ModelId",
              local.bedrock_model_id,
              {
                label = "Successful invocations"
                stat  = "Sum"
              },
            ],
            [
              "AWS/Bedrock",
              "InvocationClientErrors",
              "ModelId",
              local.bedrock_model_id,
              {
                label = "Client errors"
                stat  = "Sum"
              },
            ],
            [
              "AWS/Bedrock",
              "InvocationServerErrors",
              "ModelId",
              local.bedrock_model_id,
              {
                label = "Server errors"
                stat  = "Sum"
              },
            ],
            [
              "AWS/Bedrock",
              "InvocationThrottles",
              "ModelId",
              local.bedrock_model_id,
              {
                label = "Throttles"
                stat  = "Sum"
              },
            ],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 23
        width  = 12
        height = 6

        properties = {
          title   = "Amazon Bedrock invocation latency"
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          period  = 300
          metrics = [
            [
              "AWS/Bedrock",
              "InvocationLatency",
              "ModelId",
              local.bedrock_model_id,
              {
                label = "Invocation latency p95"
                stat  = "p95"
              },
            ],
          ]
          yAxis = {
            left = {
              label     = "Milliseconds"
              showUnits = false
            }
          }
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 29
        width  = 24
        height = 6

        properties = {
          title   = "Amazon Bedrock token usage"
          view    = "timeSeries"
          stacked = false
          region  = var.aws_region
          period  = 300
          metrics = [
            [
              "AWS/Bedrock",
              "InputTokenCount",
              "ModelId",
              local.bedrock_model_id,
              {
                label = "Input tokens"
                stat  = "Sum"
              },
            ],
            [
              "AWS/Bedrock",
              "OutputTokenCount",
              "ModelId",
              local.bedrock_model_id,
              {
                label = "Output tokens"
                stat  = "Sum"
              },
            ],
          ]
        }
      },
    ]
  })
}
