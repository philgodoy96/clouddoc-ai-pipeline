mock_provider "aws" {
  override_during = plan

  # mock_provider generates an arbitrary computed .json value, while IAM
  # resources require valid policy JSON during plan.
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
    id  = "clouddoc-test-documents"
    arn = "arn:aws:s3:::clouddoc-test-documents"
  }
}

override_resource {
  target          = aws_dynamodb_table.document_jobs
  override_during = plan

  values = {
    id  = "clouddoc-test-document-jobs"
    arn = "arn:aws:dynamodb:us-east-1:123456789012:table/clouddoc-test-document-jobs"
  }
}

override_resource {
  target          = aws_sqs_queue.processing
  override_during = plan

  values = {
    arn = "arn:aws:sqs:us-east-1:123456789012:clouddoc-test-processing"
    url = "https://sqs.us-east-1.amazonaws.com/123456789012/clouddoc-test-processing"
  }
}

override_resource {
  target          = aws_sqs_queue.processing_dlq
  override_during = plan

  values = {
    arn = "arn:aws:sqs:us-east-1:123456789012:clouddoc-test-processing-dlq"
    url = "https://sqs.us-east-1.amazonaws.com/123456789012/clouddoc-test-processing-dlq"
  }
}

override_resource {
  target          = aws_sqs_queue.reconciliation_failures
  override_during = plan

  values = {
    arn = "arn:aws:sqs:us-east-1:123456789012:clouddoc-test-reconciliation-failures"
    url = "https://sqs.us-east-1.amazonaws.com/123456789012/clouddoc-test-reconciliation-failures"
  }
}

override_resource {
  target          = aws_cloudwatch_log_group.create_job
  override_during = plan

  values = {
    arn = "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/clouddoc-test-create-job"
  }
}

override_resource {
  target          = aws_cloudwatch_log_group.get_job
  override_during = plan

  values = {
    arn = "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/clouddoc-test-get-job"
  }
}

override_resource {
  target          = aws_cloudwatch_log_group.processor
  override_during = plan

  values = {
    arn = "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/clouddoc-test-process-document"
  }
}

override_resource {
  target          = aws_cloudwatch_log_group.dead_letter_reconciler
  override_during = plan

  values = {
    arn = "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/clouddoc-test-reconcile-dead-letter"
  }
}

override_resource {
  target          = aws_cloudwatch_log_group.control_plane_api_access
  override_during = plan

  values = {
    arn  = "arn:aws:logs:us-east-1:123456789012:log-group:/aws/apigateway/clouddoc-test-control-plane"
    name = "/aws/apigateway/clouddoc-test-control-plane"
  }
}

override_resource {
  target          = aws_iam_role.create_job
  override_during = plan

  values = {
    id  = "clouddoc-test-create-job-role"
    arn = "arn:aws:iam::123456789012:role/clouddoc-test-create-job-role"
  }
}

override_resource {
  target          = aws_iam_role.get_job
  override_during = plan

  values = {
    id  = "clouddoc-test-get-job-role"
    arn = "arn:aws:iam::123456789012:role/clouddoc-test-get-job-role"
  }
}

override_resource {
  target          = aws_iam_role.processor
  override_during = plan

  values = {
    id  = "clouddoc-test-process-document-role"
    arn = "arn:aws:iam::123456789012:role/clouddoc-test-process-document-role"
  }
}

override_resource {
  target          = aws_iam_role.dead_letter_reconciler
  override_during = plan

  values = {
    id  = "clouddoc-test-reconcile-dead-letter-role"
    arn = "arn:aws:iam::123456789012:role/clouddoc-test-reconcile-dead-letter-role"
  }
}

override_resource {
  target          = aws_lambda_function.create_job
  override_during = plan

  values = {
    arn        = "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-test-create-job"
    invoke_arn = "arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:123456789012:function:clouddoc-test-create-job/invocations"
  }
}

override_resource {
  target          = aws_lambda_function.get_job
  override_during = plan

  values = {
    arn        = "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-test-get-job"
    invoke_arn = "arn:aws:apigateway:us-east-1:lambda:path/2015-03-31/functions/arn:aws:lambda:us-east-1:123456789012:function:clouddoc-test-get-job/invocations"
  }
}

override_resource {
  target          = aws_lambda_function.processor
  override_during = plan

  values = {
    arn = "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-test-process-document"
  }
}

override_resource {
  target          = aws_lambda_function.dead_letter_reconciler
  override_during = plan

  values = {
    arn = "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-test-reconcile-dead-letter"
  }
}

override_resource {
  target          = aws_apigatewayv2_api.control_plane
  override_during = plan

  values = {
    id            = "abc123"
    api_endpoint  = "https://abc123.execute-api.us-east-1.amazonaws.com"
    execution_arn = "arn:aws:execute-api:us-east-1:123456789012:abc123"
  }
}

override_resource {
  target          = aws_apigatewayv2_integration.create_job
  override_during = plan

  values = {
    id = "create-job-integration"
  }
}

override_resource {
  target          = aws_apigatewayv2_integration.get_job
  override_during = plan

  values = {
    id = "get-job-integration"
  }
}

run "control_plane_api_foundation_dev" {
  command = plan

  assert {
    condition = (
      local.control_plane_api_name ==
      "clouddoc-dev-control-plane"
    )
    error_message = "The development control-plane API name must be environment-scoped."
  }

  assert {
    condition = (
      local.control_plane_api_access_log_group_name ==
      "/aws/apigateway/clouddoc-dev-control-plane"
    )
    error_message = "The API access-log group name must be derived from the control-plane API name."
  }

  assert {
    condition = (
      local.control_plane_api_log_retention_days ==
      14
    )
    error_message = "Non-production API access logs must be retained for fourteen days."
  }

  assert {
    condition = (
      aws_apigatewayv2_api.control_plane.name ==
      local.control_plane_api_name
    )
    error_message = "The HTTP API must use the approved environment-scoped name."
  }

  assert {
    condition = (
      aws_apigatewayv2_api.control_plane.protocol_type ==
      "HTTP"
    )
    error_message = "The control-plane API must use the HTTP API protocol."
  }

  assert {
    condition = (
      aws_apigatewayv2_api.control_plane
      .disable_execute_api_endpoint ==
      false
    )
    error_message = "The default execute-api endpoint must remain enabled for controlled validation."
  }

  assert {
    condition = (
      aws_apigatewayv2_api.control_plane.tags["Name"] ==
      local.control_plane_api_name
    )
    error_message = "The API Name tag must match the environment-scoped API name."
  }

  assert {
    condition = (
      aws_apigatewayv2_api.control_plane.tags["ApiRole"] ==
      "document-job-control-plane"
    )
    error_message = "The API must be tagged as the document-job control plane."
  }

  assert {
    condition = (
      aws_cloudwatch_log_group.control_plane_api_access.name ==
      local.control_plane_api_access_log_group_name
    )
    error_message = "Terraform must own the approved API access-log group."
  }

  assert {
    condition = (
      aws_cloudwatch_log_group.control_plane_api_access
      .retention_in_days ==
      14
    )
    error_message = "The development API access-log group must retain logs for fourteen days."
  }
}

run "control_plane_api_foundation_prod" {
  command = plan

  variables {
    environment = "prod"
  }

  assert {
    condition = (
      local.control_plane_api_name ==
      "clouddoc-prod-control-plane"
    )
    error_message = "The production control-plane API name must be environment-scoped."
  }

  assert {
    condition = (
      local.control_plane_api_access_log_group_name ==
      "/aws/apigateway/clouddoc-prod-control-plane"
    )
    error_message = "The production API access-log group must use the approved environment-scoped name."
  }

  assert {
    condition = (
      local.control_plane_api_log_retention_days ==
      30
    )
    error_message = "Production API access logs must be retained for thirty days."
  }

  assert {
    condition = (
      aws_cloudwatch_log_group.control_plane_api_access
      .retention_in_days ==
      30
    )
    error_message = "The production API access-log group must use the thirty-day retention policy."
  }
}

run "control_plane_lambda_integrations" {
  command = plan

  assert {
    condition = (
      aws_apigatewayv2_integration.create_job.api_id ==
      aws_apigatewayv2_api.control_plane.id
    )
    error_message = "The Create Job integration must belong to the control-plane API."
  }

  assert {
    condition = (
      aws_apigatewayv2_integration.get_job.api_id ==
      aws_apigatewayv2_api.control_plane.id
    )
    error_message = "The Get Job integration must belong to the control-plane API."
  }

  assert {
    condition = (
      aws_apigatewayv2_integration.create_job
      .integration_type ==
      "AWS_PROXY" &&
      aws_apigatewayv2_integration.get_job
      .integration_type ==
      "AWS_PROXY"
    )
    error_message = "Both document-job integrations must use Lambda proxy integration."
  }

  assert {
    condition = (
      aws_apigatewayv2_integration.create_job
      .integration_method ==
      "POST" &&
      aws_apigatewayv2_integration.get_job
      .integration_method ==
      "POST"
    )
    error_message = "Both Lambda integrations must invoke the Lambda Invoke API with POST."
  }

  assert {
    condition = (
      aws_apigatewayv2_integration.create_job.integration_uri ==
      aws_lambda_function.create_job.invoke_arn
    )
    error_message = "The Create Job integration must target only the Create Job Lambda."
  }

  assert {
    condition = (
      aws_apigatewayv2_integration.get_job.integration_uri ==
      aws_lambda_function.get_job.invoke_arn
    )
    error_message = "The Get Job integration must target only the Get Job Lambda."
  }

  assert {
    condition = (
      aws_apigatewayv2_integration.create_job
      .payload_format_version ==
      "2.0" &&
      aws_apigatewayv2_integration.get_job
      .payload_format_version ==
      "2.0"
    )
    error_message = "Both Lambda integrations must use HTTP API payload format version 2.0."
  }

  assert {
    condition = (
      aws_apigatewayv2_integration.create_job
      .timeout_milliseconds ==
      15000
    )
    error_message = "The Create Job API integration timeout must be fifteen seconds."
  }

  assert {
    condition = (
      aws_apigatewayv2_integration.get_job
      .timeout_milliseconds ==
      10000
    )
    error_message = "The Get Job API integration timeout must be ten seconds."
  }

  assert {
    condition = (
      aws_apigatewayv2_integration.create_job
      .timeout_milliseconds >
      aws_lambda_function.create_job.timeout * 1000
    )
    error_message = "The Create Job API integration timeout must exceed the Lambda timeout."
  }

  assert {
    condition = (
      aws_apigatewayv2_integration.get_job
      .timeout_milliseconds >
      aws_lambda_function.get_job.timeout * 1000
    )
    error_message = "The Get Job API integration timeout must exceed the Lambda timeout."
  }
}

run "control_plane_routes_stage_and_throttling" {
  command = plan

  assert {
    condition = (
      aws_apigatewayv2_route.create_job.route_key ==
      "POST /v1/document-jobs"
    )
    error_message = "The Create Job route must use the approved method and path."
  }

  assert {
    condition = (
      aws_apigatewayv2_route.get_job.route_key ==
      "GET /v1/document-jobs/{job_id}"
    )
    error_message = "The Get Job route must use the approved method and path parameter."
  }

  assert {
    condition = (
      aws_apigatewayv2_route.create_job.authorization_type ==
      "AWS_IAM" &&
      aws_apigatewayv2_route.get_job.authorization_type ==
      "AWS_IAM"
    )
    error_message = "Every declared control-plane route must require AWS IAM authorization."
  }

  assert {
    condition = (
      aws_apigatewayv2_route.create_job.target ==
      "integrations/${aws_apigatewayv2_integration.create_job.id}"
    )
    error_message = "The Create Job route must target the Create Job integration."
  }

  assert {
    condition = (
      aws_apigatewayv2_route.get_job.target ==
      "integrations/${aws_apigatewayv2_integration.get_job.id}"
    )
    error_message = "The Get Job route must target the Get Job integration."
  }

  assert {
    condition = (
      aws_apigatewayv2_route.create_job.route_key != "$default" &&
      aws_apigatewayv2_route.get_job.route_key != "$default" &&
      !startswith(
        aws_apigatewayv2_route.create_job.route_key,
        "ANY ",
      ) &&
      !startswith(
        aws_apigatewayv2_route.get_job.route_key,
        "ANY ",
      )
    )
    error_message = "The control plane must not use default or wildcard routes."
  }

  assert {
    condition = (
      aws_apigatewayv2_stage.control_plane.name ==
      var.environment
    )
    error_message = "The API stage name must match the deployment environment."
  }

  assert {
    condition = (
      aws_apigatewayv2_stage.control_plane.auto_deploy
    )
    error_message = "The environment API stage must deploy route changes automatically."
  }

  assert {
    condition = (
      one(
        aws_apigatewayv2_stage.control_plane
        .access_log_settings
      ).destination_arn ==
      aws_cloudwatch_log_group.control_plane_api_access.arn
    )
    error_message = "The API stage must write access logs to the Terraform-managed log group."
  }

  assert {
    condition = (
      jsondecode(
        one(
          aws_apigatewayv2_stage.control_plane
          .access_log_settings
        ).format
      ) ==
      {
        requestId               = "$context.requestId"
        requestTimeEpoch        = "$context.requestTimeEpoch"
        routeKey                = "$context.routeKey"
        stage                   = "$context.stage"
        status                  = "$context.status"
        responseLength          = "$context.responseLength"
        integrationStatus       = "$context.integration.status"
        integrationLatency      = "$context.integrationLatency"
        integrationErrorMessage = "$context.integrationErrorMessage"
        sourceIp                = "$context.identity.sourceIp"
        userAgent               = "$context.identity.userAgent"
      }
    )
    error_message = "The API stage must emit exactly the approved structured access-log fields."
  }

  assert {
    condition = (
      one([
        for setting in
        aws_apigatewayv2_stage.control_plane.route_settings :
        setting
        if setting.route_key ==
        aws_apigatewayv2_route.create_job.route_key
      ]).throttling_rate_limit ==
      2
    )
    error_message = "The Create Job route throttling rate must be two requests per second."
  }

  assert {
    condition = (
      one([
        for setting in
        aws_apigatewayv2_stage.control_plane.route_settings :
        setting
        if setting.route_key ==
        aws_apigatewayv2_route.create_job.route_key
      ]).throttling_burst_limit ==
      5
    )
    error_message = "The Create Job route throttling burst must be five requests."
  }

  assert {
    condition = (
      one([
        for setting in
        aws_apigatewayv2_stage.control_plane.route_settings :
        setting
        if setting.route_key ==
        aws_apigatewayv2_route.get_job.route_key
      ]).throttling_rate_limit ==
      10
    )
    error_message = "The Get Job route throttling rate must be ten requests per second."
  }

  assert {
    condition = (
      one([
        for setting in
        aws_apigatewayv2_stage.control_plane.route_settings :
        setting
        if setting.route_key ==
        aws_apigatewayv2_route.get_job.route_key
      ]).throttling_burst_limit ==
      20
    )
    error_message = "The Get Job route throttling burst must be twenty requests."
  }
}

run "control_plane_lambda_permissions_and_outputs" {
  command = plan

  assert {
    condition = (
      aws_lambda_permission.control_plane_create_job.action ==
      "lambda:InvokeFunction" &&
      aws_lambda_permission.control_plane_get_job.action ==
      "lambda:InvokeFunction"
    )
    error_message = "Both API Gateway permissions must grant only Lambda invocation."
  }

  assert {
    condition = (
      aws_lambda_permission.control_plane_create_job.principal ==
      "apigateway.amazonaws.com" &&
      aws_lambda_permission.control_plane_get_job.principal ==
      "apigateway.amazonaws.com"
    )
    error_message = "Both Lambda permissions must trust only the API Gateway service principal."
  }

  assert {
    condition = (
      aws_lambda_permission.control_plane_create_job.function_name ==
      aws_lambda_function.create_job.function_name
    )
    error_message = "The Create Job permission must target only the Create Job Lambda."
  }

  assert {
    condition = (
      aws_lambda_permission.control_plane_get_job.function_name ==
      aws_lambda_function.get_job.function_name
    )
    error_message = "The Get Job permission must target only the Get Job Lambda."
  }

  assert {
    condition = (
      aws_lambda_permission.control_plane_create_job.source_arn ==
      "${aws_apigatewayv2_api.control_plane.execution_arn}/${aws_apigatewayv2_stage.control_plane.name}/POST/v1/document-jobs"
    )
    error_message = "The Create Job Lambda permission must be restricted to its stage, method, and path."
  }

  assert {
    condition = (
      aws_lambda_permission.control_plane_get_job.source_arn ==
      "${aws_apigatewayv2_api.control_plane.execution_arn}/${aws_apigatewayv2_stage.control_plane.name}/GET/v1/document-jobs/*"
    )
    error_message = "The Get Job Lambda permission must be restricted to its stage, method, and dynamic job path."
  }

  assert {
    condition = (
      aws_lambda_permission.control_plane_create_job.source_arn !=
      "${aws_apigatewayv2_api.control_plane.execution_arn}/*/*" &&
      aws_lambda_permission.control_plane_get_job.source_arn !=
      "${aws_apigatewayv2_api.control_plane.execution_arn}/*/*"
    )
    error_message = "The API Gateway Lambda permissions must not use an API-wide source ARN."
  }

  assert {
    condition = (
      output.control_plane_api_id ==
      aws_apigatewayv2_api.control_plane.id
    )
    error_message = "The API ID output must reference the control-plane API."
  }

  assert {
    condition = (
      output.control_plane_api_execution_arn ==
      aws_apigatewayv2_api.control_plane.execution_arn
    )
    error_message = "The API execution ARN output must reference the control-plane API."
  }

  assert {
    condition = (
      output.control_plane_api_base_url ==
      "https://abc123.execute-api.us-east-1.amazonaws.com/dev"
    )
    error_message = "The control-plane base URL must include the named environment stage."
  }

  assert {
    condition = (
      output.control_plane_api_stage_name ==
      aws_apigatewayv2_stage.control_plane.name
    )
    error_message = "The API stage output must reference the environment stage."
  }

  assert {
    condition = (
      output.control_plane_api_access_log_group_name ==
      aws_cloudwatch_log_group.control_plane_api_access.name
    )
    error_message = "The API access-log output must reference the managed log group."
  }
}