mock_provider "aws" {
  override_during = plan

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

variables {
  aws_region                        = "us-east-1"
  project_name                      = "clouddoc"
  noncurrent_version_retention_days = 365
}

override_data {
  target          = data.aws_caller_identity.current
  override_during = plan

  values = {
    account_id = "123456789012"
    arn        = "arn:aws:iam::123456789012:user/terraform-bootstrap-test"
    user_id    = "AIDATESTBOOTSTRAP"
  }
}

override_resource {
  target          = aws_s3_bucket.terraform_state
  override_during = plan

  values = {
    id     = "clouddoc-123456789012-terraform-state"
    bucket = "clouddoc-123456789012-terraform-state"
    arn    = "arn:aws:s3:::clouddoc-123456789012-terraform-state"
  }
}

run "terraform_state_bucket_contract" {
  command = plan

  assert {
    condition = (
      local.terraform_state_bucket_name ==
      "clouddoc-123456789012-terraform-state"
    )
    error_message = "The Terraform state bucket name must be project- and AWS-account-scoped."
  }

  assert {
    condition = (
      aws_s3_bucket.terraform_state.bucket ==
      local.terraform_state_bucket_name
    )
    error_message = "The S3 bucket resource must use the canonical account-scoped state bucket name."
  }

  assert {
    condition = (
      aws_s3_bucket.terraform_state.tags["Name"] ==
      local.terraform_state_bucket_name
    )
    error_message = "The state bucket Name tag must match its canonical bucket name."
  }

  assert {
    condition = (
      local.common_tags == {
        Project   = "clouddoc"
        ManagedBy = "terraform"
        Component = "terraform-state"
        Scope     = "account"
      }
    )
    error_message = "The bootstrap root must apply the approved account-scoped Terraform state tags."
  }
}

run "terraform_state_security_controls" {
  command = plan

  assert {
    condition = alltrue([
      aws_s3_bucket_public_access_block.terraform_state.block_public_acls,
      aws_s3_bucket_public_access_block.terraform_state.block_public_policy,
      aws_s3_bucket_public_access_block.terraform_state.ignore_public_acls,
      aws_s3_bucket_public_access_block.terraform_state.restrict_public_buckets,
    ])
    error_message = "The Terraform state bucket must block every form of public S3 access."
  }

  assert {
    condition = (
      one(
        aws_s3_bucket_ownership_controls.terraform_state.rule
      ).object_ownership == "BucketOwnerEnforced"
    )
    error_message = "The Terraform state bucket must enforce bucket-owner object ownership."
  }

  assert {
    condition = (
      one(
        one(
          aws_s3_bucket_server_side_encryption_configuration.terraform_state.rule
        ).apply_server_side_encryption_by_default
      ).sse_algorithm == "AES256"
    )
    error_message = "The Terraform state bucket must use default AES256 server-side encryption."
  }

  assert {
    condition = (
      aws_s3_bucket_policy.terraform_state.bucket ==
      aws_s3_bucket.terraform_state.id
    )
    error_message = "The HTTPS-only bucket policy must be attached to the Terraform state bucket."
  }
}

run "terraform_state_recovery_controls" {
  command = plan

  assert {
    condition = (
      one(
        aws_s3_bucket_versioning.terraform_state.versioning_configuration
      ).status == "Enabled"
    )
    error_message = "Terraform state object versioning must remain enabled for recovery."
  }

  assert {
    condition = (
      one(
        aws_s3_bucket_lifecycle_configuration.terraform_state.rule
      ).id == "terraform-state-version-retention" &&
      one(
        aws_s3_bucket_lifecycle_configuration.terraform_state.rule
      ).status == "Enabled"
    )
    error_message = "The Terraform state version-retention lifecycle rule must remain enabled."
  }

  assert {
    condition = (
      one(
        one(
          aws_s3_bucket_lifecycle_configuration.terraform_state.rule
        ).noncurrent_version_expiration
      ).noncurrent_days == 365
    )
    error_message = "Noncurrent Terraform state versions must use the configured retention period."
  }

  assert {
    condition = (
      one(
        one(
          aws_s3_bucket_lifecycle_configuration.terraform_state.rule
        ).abort_incomplete_multipart_upload
      ).days_after_initiation == 1
    )
    error_message = "Incomplete state-bucket multipart uploads must be cleaned after one day."
  }

  assert {
    condition = (
      output.terraform_state_bucket_name ==
      aws_s3_bucket.terraform_state.bucket &&
      output.terraform_state_bucket_arn ==
      aws_s3_bucket.terraform_state.arn &&
      output.terraform_state_bucket_region == "us-east-1"
    )
    error_message = "Bootstrap outputs must expose the exact bucket name, ARN, and Region."
  }
}

run "terraform_state_destroy_protection" {
  command = plan

  assert {
    condition = (
      aws_s3_bucket.terraform_state.force_destroy == false
    )
    error_message = "The Terraform state bucket must never allow routine force destruction."
  }

  assert {
    condition = (
      aws_s3_bucket_lifecycle_configuration.terraform_state.bucket ==
      aws_s3_bucket.terraform_state.id &&
      aws_s3_bucket_versioning.terraform_state.bucket ==
      aws_s3_bucket.terraform_state.id
    )
    error_message = "Recovery controls must remain attached to the protected state bucket."
  }
}