locals {
  name_prefix                        = "${var.project_name}-${var.environment}"
  documents_bucket_name              = "${local.name_prefix}-${data.aws_caller_identity.current.account_id}-documents"
  document_jobs_table_name           = "${local.name_prefix}-document-jobs"
  reconciliation_failures_queue_name = "${local.name_prefix}-reconciliation-failures"

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

  is_production             = var.environment == "prod"
  lambda_log_retention_days = local.is_production ? 30 : 14

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Component   = "document-processing"
  }
}
