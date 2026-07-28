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

output "terraform_apply_role_name" {
  description = "Canonical name of the CloudDoc development Terraform apply authorization role."
  value       = aws_iam_role.terraform_apply.name
}

output "terraform_apply_role_arn" {
  description = "ARN of the CloudDoc development Terraform apply authorization role assumed only by the deployment identity."
  value       = aws_iam_role.terraform_apply.arn
}

output "terraform_apply_role_max_session_duration" {
  description = "Maximum session duration configured on the Terraform apply authorization role."
  value       = aws_iam_role.terraform_apply.max_session_duration
}

output "github_identity_role_arn" {
  description = "Exact same-account GitHub identity role ARN trusted by the state and plan roles."
  value       = local.github_identity_role_arn
}

output "github_deploy_identity_role_arn" {
  description = "Exact same-account GitHub deployment identity role ARN trusted only by the state and apply roles."
  value       = local.github_deploy_identity_role_arn
}

output "terraform_state_trusted_identity_role_arns" {
  description = "Exact two-principal allowlist trusted by the Terraform state role: the plan identity and deployment identity only."
  value       = local.terraform_state_trusted_identity_role_arns
}

output "terraform_apply_trusted_identity_role_arn" {
  description = "Exact deployment identity ARN trusted by the Terraform apply role, which excludes the plan identity and direct OIDC trust."
  value       = local.github_deploy_identity_role_arn
}

output "lambda_execution_role_arns" {
  description = "Exact Lambda execution-role ARNs that the apply role may manage and pass only to the Lambda service."
  value       = local.lambda_execution_role_arns
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
