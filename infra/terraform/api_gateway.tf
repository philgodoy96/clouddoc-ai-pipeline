resource "aws_apigatewayv2_api" "control_plane" {
  name          = local.control_plane_api_name
  description   = "Authenticated HTTP control plane for CloudDoc document job operations."
  protocol_type = "HTTP"

  disable_execute_api_endpoint = false

  tags = {
    Name    = local.control_plane_api_name
    ApiRole = "document-job-control-plane"
  }
}

resource "aws_cloudwatch_log_group" "control_plane_api_access" {
  name              = local.control_plane_api_access_log_group_name
  retention_in_days = local.control_plane_api_log_retention_days

  tags = {
    Name    = local.control_plane_api_access_log_group_name
    LogRole = "api-access"
  }
}

resource "aws_apigatewayv2_integration" "create_job" {
  api_id = aws_apigatewayv2_api.control_plane.id

  integration_type   = "AWS_PROXY"
  integration_method = "POST"
  integration_uri    = aws_lambda_function.create_job.invoke_arn

  payload_format_version = "2.0"
  timeout_milliseconds   = 15000
}

resource "aws_apigatewayv2_integration" "get_job" {
  api_id = aws_apigatewayv2_api.control_plane.id

  integration_type   = "AWS_PROXY"
  integration_method = "POST"
  integration_uri    = aws_lambda_function.get_job.invoke_arn

  payload_format_version = "2.0"
  timeout_milliseconds   = 10000
}

resource "aws_apigatewayv2_route" "create_job" {
  api_id = aws_apigatewayv2_api.control_plane.id

  route_key          = "POST /v1/document-jobs"
  authorization_type = "AWS_IAM"

  target = "integrations/${aws_apigatewayv2_integration.create_job.id}"
}

resource "aws_apigatewayv2_route" "get_job" {
  api_id = aws_apigatewayv2_api.control_plane.id

  route_key          = "GET /v1/document-jobs/{job_id}"
  authorization_type = "AWS_IAM"

  target = "integrations/${aws_apigatewayv2_integration.get_job.id}"
}

resource "aws_apigatewayv2_stage" "control_plane" {
  api_id = aws_apigatewayv2_api.control_plane.id
  name   = var.environment

  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.control_plane_api_access.arn

    format = jsonencode({
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
    })
  }

  route_settings {
    route_key = aws_apigatewayv2_route.create_job.route_key

    throttling_rate_limit  = 2
    throttling_burst_limit = 5
  }

  route_settings {
    route_key = aws_apigatewayv2_route.get_job.route_key

    throttling_rate_limit  = 10
    throttling_burst_limit = 20
  }

  tags = {
    Name      = "${local.control_plane_api_name}-${var.environment}"
    StageRole = "document-job-control-plane"
  }
}