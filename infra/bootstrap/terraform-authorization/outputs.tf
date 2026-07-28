output "terraform_state_role_name" {
  description = "Canonical name of the CloudDoc development Terraform state authorization role."
  value       = aws_iam_role.terraform_state.name
}

output "terraform_state_role_arn" {
  description = "ARN of the CloudDoc development Terraform state authorization role assumed by the S3 backend."
  value       = aws_iam_role.terraform_state.arn
}

output "terraform_state_role_max_session_duration" {
  description = "Maximum session duration configured on the Terraform state authorization role."
  value       = aws_iam_role.terraform_state.max_session_duration
}

output "terraform_plan_role_name" {
  description = "Canonical name of the CloudDoc development Terraform plan authorization role."
  value       = aws_iam_role.terraform_plan.name
}

output "terraform_plan_role_arn" {
  description = "ARN of the CloudDoc development Terraform plan authorization role assumed by the AWS provider."
  value       = aws_iam_role.terraform_plan.arn
}

output "terraform_plan_role_max_session_duration" {
  description = "Maximum session duration configured on the Terraform plan authorization role."
  value       = aws_iam_role.terraform_plan.max_session_duration
}

output "github_identity_role_arn" {
  description = "Exact same-account GitHub identity role ARN trusted by the state and plan roles."
  value       = local.github_identity_role_arn
}

output "terraform_state_bucket_name" {
  description = "Account-scoped S3 bucket that stores the CloudDoc development Terraform state object."
  value       = var.terraform_state_bucket_name
}

output "terraform_state_key" {
  description = "Exact object key of the CloudDoc development Terraform state."
  value       = var.terraform_state_key
}

output "terraform_lock_key" {
  description = "Exact object key of the S3-native Terraform lock for the development state."
  value       = local.terraform_lock_key
}

output "terraform_state_object_arn" {
  description = "ARN of the exact development Terraform state object authorized for the state role."
  value       = local.terraform_state_object_arn
}

output "terraform_lock_object_arn" {
  description = "ARN of the exact development Terraform lock object authorized for the state role."
  value       = local.terraform_lock_object_arn
}
