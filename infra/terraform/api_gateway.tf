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