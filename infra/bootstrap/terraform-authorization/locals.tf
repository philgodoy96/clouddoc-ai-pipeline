locals {
  terraform_state_role_name   = "clouddoc-dev-terraform-state"
  terraform_plan_role_name    = "clouddoc-dev-terraform-plan"
  terraform_state_policy_name = "clouddoc-dev-terraform-state-access"
  terraform_plan_policy_name  = "clouddoc-dev-terraform-plan-access"

  terraform_lock_key = "${var.terraform_state_key}.tflock"

  github_identity_role_arn = (
    "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/${var.github_identity_role_name}"
  )

  terraform_state_bucket_arn = (
    "arn:${data.aws_partition.current.partition}:s3:::${var.terraform_state_bucket_name}"
  )
  terraform_state_object_arn = (
    "${local.terraform_state_bucket_arn}/${var.terraform_state_key}"
  )
  terraform_lock_object_arn = (
    "${local.terraform_state_bucket_arn}/${local.terraform_lock_key}"
  )

  role_max_session_duration = 3600

  # Application naming contracts mirrored from infra/terraform/locals.tf.
  name_prefix                             = "${var.project_name}-${var.environment}"
  documents_bucket_name                   = "${local.name_prefix}-${var.aws_account_id}-documents"
  document_jobs_table_name                = "${local.name_prefix}-document-jobs"
  reconciliation_failures_queue_name      = "${local.name_prefix}-reconciliation-failures"
  control_plane_api_name                  = "${local.name_prefix}-control-plane"
  control_plane_api_access_log_group_name = "/aws/apigateway/${local.control_plane_api_name}"
  create_job_function_name                = "${local.name_prefix}-create-job"
  get_job_function_name                   = "${local.name_prefix}-get-job"
  processor_function_name                 = "${local.name_prefix}-process-document"
  dead_letter_reconciler_function_name    = "${local.name_prefix}-reconcile-dead-letter"
  processing_queue_name                   = "${local.name_prefix}-processing"
  processing_dlq_name                     = "${local.name_prefix}-processing-dlq"
  operations_dashboard_name               = "${local.name_prefix}-operations"

  create_job_role_name             = "${local.create_job_function_name}-role"
  get_job_role_name                = "${local.get_job_function_name}-role"
  processor_role_name              = "${local.processor_function_name}-role"
  dead_letter_reconciler_role_name = "${local.dead_letter_reconciler_function_name}-role"

  documents_bucket_arn = (
    "arn:${data.aws_partition.current.partition}:s3:::${local.documents_bucket_name}"
  )

  document_jobs_table_arn = (
    "arn:${data.aws_partition.current.partition}:dynamodb:${var.aws_region}:${var.aws_account_id}:table/${local.document_jobs_table_name}"
  )

  application_iam_role_arns = [
    "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/${local.create_job_role_name}",
    "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/${local.get_job_role_name}",
    "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/${local.processor_role_name}",
    "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/${local.dead_letter_reconciler_role_name}",
  ]

  application_lambda_function_arns = [
    "arn:${data.aws_partition.current.partition}:lambda:${var.aws_region}:${var.aws_account_id}:function:${local.create_job_function_name}",
    "arn:${data.aws_partition.current.partition}:lambda:${var.aws_region}:${var.aws_account_id}:function:${local.get_job_function_name}",
    "arn:${data.aws_partition.current.partition}:lambda:${var.aws_region}:${var.aws_account_id}:function:${local.processor_function_name}",
    "arn:${data.aws_partition.current.partition}:lambda:${var.aws_region}:${var.aws_account_id}:function:${local.dead_letter_reconciler_function_name}",
  ]

  # Event-source mapping UUIDs are assigned by AWS during create/refresh.
  application_lambda_event_source_mapping_arn_prefix = (
    "arn:${data.aws_partition.current.partition}:lambda:${var.aws_region}:${var.aws_account_id}:event-source-mapping/*"
  )

  application_sqs_queue_arns = [
    "arn:${data.aws_partition.current.partition}:sqs:${var.aws_region}:${var.aws_account_id}:${local.processing_queue_name}",
    "arn:${data.aws_partition.current.partition}:sqs:${var.aws_region}:${var.aws_account_id}:${local.processing_dlq_name}",
    "arn:${data.aws_partition.current.partition}:sqs:${var.aws_region}:${var.aws_account_id}:${local.reconciliation_failures_queue_name}",
  ]

  application_log_group_arns = [
    "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${var.aws_account_id}:log-group:/aws/lambda/${local.create_job_function_name}",
    "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${var.aws_account_id}:log-group:/aws/lambda/${local.get_job_function_name}",
    "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${var.aws_account_id}:log-group:/aws/lambda/${local.processor_function_name}",
    "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${var.aws_account_id}:log-group:/aws/lambda/${local.dead_letter_reconciler_function_name}",
    "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${var.aws_account_id}:log-group:${local.control_plane_api_access_log_group_name}",
  ]

  application_alarm_arn_prefix = (
    "arn:${data.aws_partition.current.partition}:cloudwatch:${var.aws_region}:${var.aws_account_id}:alarm:${local.name_prefix}-*"
  )

  operations_dashboard_arn = (
    "arn:${data.aws_partition.current.partition}:cloudwatch::${var.aws_account_id}:dashboard/${local.operations_dashboard_name}"
  )

  common_tags = {
    Project     = var.project_name
    ManagedBy   = "terraform"
    Component   = "terraform-authorization"
    Scope       = "account"
    Environment = var.environment
  }
}
