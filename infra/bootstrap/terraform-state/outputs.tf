output "terraform_state_bucket_name" {
  description = "Name of the account-scoped CloudDoc Terraform state bucket."
  value       = aws_s3_bucket.terraform_state.bucket
}

output "terraform_state_bucket_arn" {
  description = "ARN of the account-scoped CloudDoc Terraform state bucket."
  value       = aws_s3_bucket.terraform_state.arn
}

output "terraform_state_bucket_region" {
  description = "AWS Region containing the CloudDoc Terraform state bucket."
  value       = var.aws_region
}