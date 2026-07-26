locals {
  name_prefix           = "${var.project_name}-${var.environment}"
  documents_bucket_name = "${local.name_prefix}-${data.aws_caller_identity.current.account_id}-documents"

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
    Component   = "document-processing"
  }
}
