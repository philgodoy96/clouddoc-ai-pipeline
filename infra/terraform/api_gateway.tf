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