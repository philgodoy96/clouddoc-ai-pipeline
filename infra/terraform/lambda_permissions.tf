resource "aws_lambda_permission" "control_plane_create_job" {
  statement_id = "AllowControlPlaneCreateJobInvocation"
  action       = "lambda:InvokeFunction"

  function_name = aws_lambda_function.create_job.function_name
  principal     = "apigateway.amazonaws.com"

  source_arn = "${aws_apigatewayv2_api.control_plane.execution_arn}/${aws_apigatewayv2_stage.control_plane.name}/POST/v1/document-jobs"
}

resource "aws_lambda_permission" "control_plane_get_job" {
  statement_id = "AllowControlPlaneGetJobInvocation"
  action       = "lambda:InvokeFunction"

  function_name = aws_lambda_function.get_job.function_name
  principal     = "apigateway.amazonaws.com"

  source_arn = "${aws_apigatewayv2_api.control_plane.execution_arn}/${aws_apigatewayv2_stage.control_plane.name}/GET/v1/document-jobs/*"
}