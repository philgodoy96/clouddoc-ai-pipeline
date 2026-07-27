locals {
  name_prefix                             = "${var.project_name}-${var.environment}"
  documents_bucket_name                   = "${local.name_prefix}-${data.aws_caller_identity.current.account_id}-documents"
  document_jobs_table_name                = "${local.name_prefix}-document-jobs"
  reconciliation_failures_queue_name      = "${local.name_prefix}-reconciliation-failures"
  control_plane_api_name                  = "${local.name_prefix}-control-plane"
  control_plane_api_access_log_group_name = "/aws/apigateway/${local.control_plane_api_name}"

  create_job_function_name             = "${local.name_prefix}-create-job"
  get_job_function_name                = "${local.name_prefix}-get-job"
  processor_function_name              = "${local.name_prefix}-process-document"
  dead_letter_reconciler_function_name = "${local.name_prefix}-reconcile-dead-letter"

  lambda_artifact_path    = abspath("${path.module}/../../artifacts/lambda/clouddoc-app.zip")
  lambda_source_code_hash = fileexists(local.lambda_artifact_path) ? filebase64sha256(local.lambda_artifact_path) : null

  lambda_runtime_environment = tomap({
    CLOUDDOC_JOBS_TABLE_NAME                   = aws_dynamodb_table.document_jobs.name
    CLOUDDOC_DOCUMENTS_BUCKET_NAME             = aws_s3_bucket.documents.bucket
    CLOUDDOC_UPLOAD_URL_EXPIRATION_SECONDS     = "900"
    CLOUDDOC_PROCESSING_LEASE_DURATION_SECONDS = "300"
    CLOUDDOC_MAX_DOCUMENT_SIZE_BYTES           = "65536"
  })

  bedrock_model_id             = "amazon.nova-micro-v1:0"
  bedrock_max_output_tokens    = "1200"
  bedrock_temperature          = "0.00001"
  bedrock_foundation_model_arn = "arn:${data.aws_partition.current.partition}:bedrock:${var.aws_region}::foundation-model/${local.bedrock_model_id}"

  processor_runtime_environment = tomap(merge(
    local.lambda_runtime_environment,
    {
      CLOUDDOC_AI_PROVIDER               = "bedrock"
      CLOUDDOC_BEDROCK_MODEL_ID          = local.bedrock_model_id
      CLOUDDOC_BEDROCK_MAX_OUTPUT_TOKENS = local.bedrock_max_output_tokens
      CLOUDDOC_BEDROCK_TEMPERATURE       = local.bedrock_temperature
    },
  ))

  is_production                        = var.environment == "prod"
  lambda_log_retention_days            = local.is_production ? 30 : 14
  control_plane_api_log_retention_days = local.is_production ? 30 : 14

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Component   = "document-processing"
  }
}
