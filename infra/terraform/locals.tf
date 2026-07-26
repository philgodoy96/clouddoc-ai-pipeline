locals {
  name_prefix              = "${var.project_name}-${var.environment}"
  documents_bucket_name    = "${local.name_prefix}-${data.aws_caller_identity.current.account_id}-documents"
  document_jobs_table_name = "${local.name_prefix}-document-jobs"

  create_job_function_name             = "${local.name_prefix}-create-job"
  get_job_function_name                = "${local.name_prefix}-get-job"
  processor_function_name              = "${local.name_prefix}-process-document"
  dead_letter_reconciler_function_name = "${local.name_prefix}-reconcile-dead-letter"

  is_production             = var.environment == "prod"
  lambda_log_retention_days = local.is_production ? 30 : 14

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Component   = "document-processing"
  }
}
