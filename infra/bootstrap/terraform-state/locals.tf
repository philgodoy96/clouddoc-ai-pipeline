locals {
  terraform_state_bucket_name = "${var.project_name}-${data.aws_caller_identity.current.account_id}-terraform-state"

  common_tags = {
    Project   = var.project_name
    ManagedBy = "terraform"
    Component = "terraform-state"
    Scope     = "account"
  }
}