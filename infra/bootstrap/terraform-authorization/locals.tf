locals {
  terraform_state_role_name   = "clouddoc-dev-terraform-state"
  terraform_plan_role_name    = "clouddoc-dev-terraform-plan"
  terraform_apply_role_name   = "clouddoc-dev-terraform-apply"
  terraform_state_policy_name = "clouddoc-dev-terraform-state-access"
  terraform_plan_policy_name  = "clouddoc-dev-terraform-plan-access"
  terraform_apply_policy_name = "clouddoc-dev-terraform-apply-access"

  terraform_lock_key = "${var.terraform_state_key}.tflock"

  github_identity_role_arn = (
    "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/${var.github_identity_role_name}"
  )
  github_deploy_identity_role_arn = (
    "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/${var.github_deploy_identity_role_name}"
  )
  terraform_state_trusted_identity_role_arns = sort([
    local.github_identity_role_arn,
    local.github_deploy_identity_role_arn,
  ])

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
  create_job_role_arn              = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/${local.create_job_role_name}"
  get_job_role_arn                 = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/${local.get_job_role_name}"
  processor_role_arn               = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/${local.processor_role_name}"
  dead_letter_reconciler_role_arn  = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/${local.dead_letter_reconciler_role_name}"

  documents_bucket_arn = (
    "arn:${data.aws_partition.current.partition}:s3:::${local.documents_bucket_name}"
  )

  document_jobs_table_arn = (
    "arn:${data.aws_partition.current.partition}:dynamodb:${var.aws_region}:${var.aws_account_id}:table/${local.document_jobs_table_name}"
  )

  lambda_execution_role_arns = sort([
    local.create_job_role_arn,
    local.get_job_role_arn,
    local.processor_role_arn,
    local.dead_letter_reconciler_role_arn,
  ])

  application_iam_role_arns = local.lambda_execution_role_arns

  application_lambda_function_arns = [
    "arn:${data.aws_partition.current.partition}:lambda:${var.aws_region}:${var.aws_account_id}:function:${local.create_job_function_name}",
    "arn:${data.aws_partition.current.partition}:lambda:${var.aws_region}:${var.aws_account_id}:function:${local.get_job_function_name}",
    "arn:${data.aws_partition.current.partition}:lambda:${var.aws_region}:${var.aws_account_id}:function:${local.processor_function_name}",
    "arn:${data.aws_partition.current.partition}:lambda:${var.aws_region}:${var.aws_account_id}:function:${local.dead_letter_reconciler_function_name}",
  ]

  # Event-source mapping create is constrained by lambda:FunctionArn to these
  # SQS consumer functions only (processor and dead-letter reconciler).
  application_lambda_event_source_mapping_function_arns = sort([
    "arn:${data.aws_partition.current.partition}:lambda:${var.aws_region}:${var.aws_account_id}:function:${local.processor_function_name}",
    "arn:${data.aws_partition.current.partition}:lambda:${var.aws_region}:${var.aws_account_id}:function:${local.dead_letter_reconciler_function_name}",
  ])

  application_apigateway_apis_resource = (
    "arn:${data.aws_partition.current.partition}:apigateway:${var.aws_region}::/apis"
  )
  application_apigateway_api_resource_prefix = (
    "arn:${data.aws_partition.current.partition}:apigateway:${var.aws_region}::/apis/*"
  )
  application_apigateway_integrations_resource = (
    "arn:${data.aws_partition.current.partition}:apigateway:${var.aws_region}::/apis/*/integrations"
  )
  application_apigateway_integration_resource_prefix = (
    "arn:${data.aws_partition.current.partition}:apigateway:${var.aws_region}::/apis/*/integrations/*"
  )
  application_apigateway_routes_resource = (
    "arn:${data.aws_partition.current.partition}:apigateway:${var.aws_region}::/apis/*/routes"
  )
  application_apigateway_route_resource_prefix = (
    "arn:${data.aws_partition.current.partition}:apigateway:${var.aws_region}::/apis/*/routes/*"
  )
  application_apigateway_stages_resource = (
    "arn:${data.aws_partition.current.partition}:apigateway:${var.aws_region}::/apis/*/stages"
  )
  application_apigateway_stage_resource_prefix = (
    "arn:${data.aws_partition.current.partition}:apigateway:${var.aws_region}::/apis/*/stages/*"
  )
  # Tagged CreateApi authorizes against the URL-encoded API Gateway tag resource.
  application_apigateway_api_tag_resource = (
    "arn:${data.aws_partition.current.partition}:apigateway:${var.aws_region}::/tags/arn%3A${data.aws_partition.current.partition}%3Aapigateway%3A${var.aws_region}%3A%3A%2Fv2%2Fapis%2F*"
  )
  # Stage TagResource authorizes against the URL-encoded Stage tag resource.
  application_apigateway_stage_tag_resource = (
    "arn:${data.aws_partition.current.partition}:apigateway:${var.aws_region}::/tags/arn%3A${data.aws_partition.current.partition}%3Aapigateway%3A${var.aws_region}%3A%3A%2Fv2%2Fapis%2F*%2Fstages%2F*"
  )

  application_sqs_queue_arns = [
    "arn:${data.aws_partition.current.partition}:sqs:${var.aws_region}:${var.aws_account_id}:${local.processing_queue_name}",
    "arn:${data.aws_partition.current.partition}:sqs:${var.aws_region}:${var.aws_account_id}:${local.processing_dlq_name}",
    "arn:${data.aws_partition.current.partition}:sqs:${var.aws_region}:${var.aws_account_id}:${local.reconciliation_failures_queue_name}",
  ]

  # Bare log-group ARNs for logs:ListTagsForResource (Plan tagging).
  application_log_group_arns = [
    "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${var.aws_account_id}:log-group:/aws/lambda/${local.create_job_function_name}",
    "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${var.aws_account_id}:log-group:/aws/lambda/${local.get_job_function_name}",
    "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${var.aws_account_id}:log-group:/aws/lambda/${local.processor_function_name}",
    "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${var.aws_account_id}:log-group:/aws/lambda/${local.dead_letter_reconciler_function_name}",
    "arn:${data.aws_partition.current.partition}:logs:${var.aws_region}:${var.aws_account_id}:log-group:${local.control_plane_api_access_log_group_name}",
  ]

  # Management form (trailing :*) for CreateLogGroup and related Apply actions.
  application_log_group_management_arns = [
    for arn in local.application_log_group_arns : "${arn}:*"
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
