mock_provider "aws" {
  override_during = plan

  # mock_provider invents a random string for computed .json; IAM resources
  # validate that attribute as a JSON object, so supply a minimal valid policy.
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

variables {
  aws_region   = "us-east-1"
  project_name = "clouddoc"
  environment  = "dev"
}

override_data {
  target          = data.aws_caller_identity.current
  override_during = plan

  values = {
    account_id = "123456789012"
  }
}

override_resource {
  target          = aws_s3_bucket.documents
  override_during = plan

  values = {
    id  = "clouddoc-dev-123456789012-documents"
    arn = "arn:aws:s3:::clouddoc-dev-123456789012-documents"
  }
}

override_resource {
  target          = aws_sqs_queue.processing
  override_during = plan

  values = {
    arn = "arn:aws:sqs:us-east-1:123456789012:clouddoc-dev-processing"
    url = "https://sqs.us-east-1.amazonaws.com/123456789012/clouddoc-dev-processing"
  }
}

run "private_document_ingestion_topology" {
  command = plan

  assert {
    condition = (
      local.documents_bucket_name ==
      "clouddoc-dev-123456789012-documents"
    )
    error_message = "The documents bucket name must include the project, environment, and AWS account ID."
  }

  assert {
    condition = (
      aws_s3_bucket.documents.bucket ==
      local.documents_bucket_name
    )
    error_message = "The documents bucket must use the account-scoped bucket name."
  }

  assert {
    condition     = aws_s3_bucket.documents.force_destroy == false
    error_message = "The documents bucket must not allow force deletion."
  }

  assert {
    condition = (
      aws_s3_bucket.documents.tags["Name"] ==
      local.documents_bucket_name
    )
    error_message = "The documents bucket Name tag must match the bucket name."
  }

  assert {
    condition = (
      aws_s3_bucket.documents.tags["BucketRole"] ==
      "document-source"
    )
    error_message = "The documents bucket must be tagged as the document source."
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.documents.bucket ==
      aws_s3_bucket.documents.id
    )
    error_message = "The public-access block must target the documents bucket."
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.documents
      .block_public_acls
    )
    error_message = "The documents bucket must block public ACLs."
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.documents
      .block_public_policy
    )
    error_message = "The documents bucket must block public bucket policies."
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.documents
      .ignore_public_acls
    )
    error_message = "The documents bucket must ignore public ACLs."
  }

  assert {
    condition = (
      aws_s3_bucket_public_access_block.documents
      .restrict_public_buckets
    )
    error_message = "The documents bucket must restrict public access."
  }

  assert {
    condition = (
      aws_s3_bucket_ownership_controls.documents.bucket ==
      aws_s3_bucket.documents.id
    )
    error_message = "Object ownership controls must target the documents bucket."
  }

  assert {
    condition = (
      one(
        aws_s3_bucket_ownership_controls.documents.rule
      ).object_ownership ==
      "BucketOwnerEnforced"
    )
    error_message = "The documents bucket must disable ACL-based ownership."
  }

  assert {
    condition = (
      aws_s3_bucket_server_side_encryption_configuration
      .documents.bucket ==
      aws_s3_bucket.documents.id
    )
    error_message = "Encryption configuration must target the documents bucket."
  }

  assert {
    condition = (
      one(
        one(
          aws_s3_bucket_server_side_encryption_configuration
          .documents.rule
        ).apply_server_side_encryption_by_default
      ).sse_algorithm ==
      "AES256"
    )
    error_message = "The documents bucket must use SSE-S3 encryption."
  }

  assert {
    condition = (
      aws_s3_bucket_versioning.documents.bucket ==
      aws_s3_bucket.documents.id
    )
    error_message = "Versioning configuration must target the documents bucket."
  }

  assert {
    condition = (
      one(
        aws_s3_bucket_versioning.documents
        .versioning_configuration
      ).status ==
      "Enabled"
    )
    error_message = "Document-bucket versioning must be enabled."
  }

  assert {
    condition = (
      aws_s3_bucket_lifecycle_configuration.documents.bucket ==
      aws_s3_bucket.documents.id
    )
    error_message = "Lifecycle configuration must target the documents bucket."
  }

  assert {
    condition = (
      one(
        aws_s3_bucket_lifecycle_configuration.documents.rule
      ).id ==
      "documents-retention"
    )
    error_message = "The document-retention lifecycle rule must have a stable identifier."
  }

  assert {
    condition = (
      one(
        aws_s3_bucket_lifecycle_configuration.documents.rule
      ).status ==
      "Enabled"
    )
    error_message = "The document-retention lifecycle rule must be enabled."
  }

  assert {
    condition = (
      one(
        one(
          aws_s3_bucket_lifecycle_configuration.documents.rule
        ).filter
      ).prefix ==
      "documents/"
    )
    error_message = "The lifecycle rule must apply to the documents prefix."
  }

  assert {
    condition = (
      one(
        one(
          aws_s3_bucket_lifecycle_configuration.documents.rule
        ).expiration
      ).days ==
      30
    )
    error_message = "Current document versions must expire after thirty days."
  }

  assert {
    condition = (
      one(
        one(
          aws_s3_bucket_lifecycle_configuration.documents.rule
        ).noncurrent_version_expiration
      ).noncurrent_days ==
      30
    )
    error_message = "Noncurrent document versions must expire after thirty days."
  }

  assert {
    condition = (
      one(
        one(
          aws_s3_bucket_lifecycle_configuration.documents.rule
        ).abort_incomplete_multipart_upload
      ).days_after_initiation ==
      1
    )
    error_message = "Incomplete multipart uploads must be aborted after one day."
  }

  assert {
    condition = (
      aws_s3_bucket_policy.documents.bucket ==
      aws_s3_bucket.documents.id
    )
    error_message = "The HTTPS-only policy must be attached to the documents bucket."
  }

  assert {
    condition = (
      length(
        data.aws_iam_policy_document
        .documents_https_only.statement
      ) ==
      1
    )
    error_message = "The HTTPS-only policy must contain exactly one statement."
  }

  assert {
    condition = (
      one(
        data.aws_iam_policy_document
        .documents_https_only.statement
      ).sid ==
      "DenyInsecureTransport"
    )
    error_message = "The HTTPS-only policy must use the expected statement identifier."
  }

  assert {
    condition = (
      one(
        data.aws_iam_policy_document
        .documents_https_only.statement
      ).effect ==
      "Deny"
    )
    error_message = "The HTTPS-only policy must explicitly deny insecure requests."
  }

  assert {
    condition = (
      length(
        one(
          data.aws_iam_policy_document
          .documents_https_only.statement
        ).actions
      ) ==
      1 &&
      contains(
        one(
          data.aws_iam_policy_document
          .documents_https_only.statement
        ).actions,
        "s3:*",
      )
    )
    error_message = "The HTTPS-only policy must deny insecure S3 operations."
  }

  assert {
    condition = (
      length(
        one(
          data.aws_iam_policy_document
          .documents_https_only.statement
        ).resources
      ) ==
      2 &&
      contains(
        one(
          data.aws_iam_policy_document
          .documents_https_only.statement
        ).resources,
        aws_s3_bucket.documents.arn,
      ) &&
      contains(
        one(
          data.aws_iam_policy_document
          .documents_https_only.statement
        ).resources,
        "${aws_s3_bucket.documents.arn}/*",
      )
    )
    error_message = "The HTTPS-only policy must protect the bucket and its objects."
  }

  assert {
    condition = (
      length(
        one(
          data.aws_iam_policy_document
          .documents_https_only.statement
        ).principals
      ) ==
      1 &&
      one(
        one(
          data.aws_iam_policy_document
          .documents_https_only.statement
        ).principals
      ).type ==
      "*" &&
      contains(
        one(
          one(
            data.aws_iam_policy_document
            .documents_https_only.statement
          ).principals
        ).identifiers,
        "*",
      )
    )
    error_message = "The insecure-transport deny must apply to every principal."
  }

  assert {
    condition = (
      length([
        for condition in one(
          data.aws_iam_policy_document
          .documents_https_only.statement
        ).condition : condition
        if(
          condition.test == "Bool" &&
          condition.variable == "aws:SecureTransport" &&
          length(condition.values) == 1 &&
          contains(condition.values, "false")
        )
      ]) ==
      1
    )
    error_message = "The bucket policy must deny requests when aws:SecureTransport is false."
  }

  assert {
    condition = (
      data.aws_iam_policy_document
      .processing_queue_allow_s3.version ==
      "2012-10-17"
    )
    error_message = "The processing queue policy must use IAM policy version 2012-10-17."
  }

  assert {
    condition = (
      length(
        data.aws_iam_policy_document
        .processing_queue_allow_s3.statement
      ) ==
      1
    )
    error_message = "The S3 publishing policy must contain exactly one statement."
  }

  assert {
    condition = (
      one(
        data.aws_iam_policy_document
        .processing_queue_allow_s3.statement
      ).sid ==
      "AllowDocumentBucketNotifications"
    )
    error_message = "The S3 publishing permission must use the expected statement identifier."
  }

  assert {
    condition = (
      one(
        data.aws_iam_policy_document
        .processing_queue_allow_s3.statement
      ).effect ==
      "Allow"
    )
    error_message = "The S3 publishing statement must explicitly allow delivery."
  }

  assert {
    condition = (
      length(
        one(
          data.aws_iam_policy_document
          .processing_queue_allow_s3.statement
        ).principals
      ) ==
      1 &&
      one(
        one(
          data.aws_iam_policy_document
          .processing_queue_allow_s3.statement
        ).principals
      ).type ==
      "Service" &&
      length(
        one(
          one(
            data.aws_iam_policy_document
            .processing_queue_allow_s3.statement
          ).principals
        ).identifiers
      ) ==
      1 &&
      contains(
        one(
          one(
            data.aws_iam_policy_document
            .processing_queue_allow_s3.statement
          ).principals
        ).identifiers,
        "s3.amazonaws.com",
      )
    )
    error_message = "Only the Amazon S3 service principal may publish document notifications."
  }

  assert {
    condition = (
      length(
        one(
          data.aws_iam_policy_document
          .processing_queue_allow_s3.statement
        ).actions
      ) ==
      1 &&
      contains(
        one(
          data.aws_iam_policy_document
          .processing_queue_allow_s3.statement
        ).actions,
        "sqs:SendMessage",
      )
    )
    error_message = "The S3 service principal must receive only sqs:SendMessage."
  }

  assert {
    condition = (
      length(
        one(
          data.aws_iam_policy_document
          .processing_queue_allow_s3.statement
        ).resources
      ) ==
      1 &&
      contains(
        one(
          data.aws_iam_policy_document
          .processing_queue_allow_s3.statement
        ).resources,
        aws_sqs_queue.processing.arn,
      )
    )
    error_message = "The S3 publishing permission must target only the processing queue."
  }

  assert {
    condition = (
      length([
        for condition in one(
          data.aws_iam_policy_document
          .processing_queue_allow_s3.statement
        ).condition : condition
        if(
          condition.test == "ArnEquals" &&
          condition.variable == "aws:SourceArn" &&
          length(condition.values) == 1 &&
          contains(
            condition.values,
            aws_s3_bucket.documents.arn,
          )
        )
      ]) ==
      1
    )
    error_message = "The processing queue policy must restrict publication to the documents bucket ARN."
  }

  assert {
    condition = (
      length([
        for condition in one(
          data.aws_iam_policy_document
          .processing_queue_allow_s3.statement
        ).condition : condition
        if(
          condition.test == "StringEquals" &&
          condition.variable == "aws:SourceAccount" &&
          length(condition.values) == 1 &&
          contains(
            condition.values,
            data.aws_caller_identity.current.account_id,
          )
        )
      ]) ==
      1
    )
    error_message = "The processing queue policy must restrict publication to the current AWS account."
  }

  assert {
    condition = (
      aws_sqs_queue_policy.processing_s3_publish.queue_url ==
      aws_sqs_queue.processing.url
    )
    error_message = "The S3 publishing policy must be attached to the processing queue."
  }

  assert {
    condition = (
      aws_s3_bucket_notification.documents.bucket ==
      aws_s3_bucket.documents.id
    )
    error_message = "The notification configuration must belong to the documents bucket."
  }

  assert {
    condition = (
      length(
        aws_s3_bucket_notification.documents.queue
      ) ==
      1
    )
    error_message = "The documents bucket must have exactly one SQS notification destination."
  }

  assert {
    condition = (
      one(
        aws_s3_bucket_notification.documents.queue
      ).id ==
      "document-upload-created"
    )
    error_message = "The upload notification must use the stable document-upload identifier."
  }

  assert {
    condition = (
      one(
        aws_s3_bucket_notification.documents.queue
      ).queue_arn ==
      aws_sqs_queue.processing.arn
    )
    error_message = "Document-upload notifications must target the processing queue."
  }

  assert {
    condition = (
      length(
        one(
          aws_s3_bucket_notification.documents.queue
        ).events
      ) ==
      1 &&
      contains(
        one(
          aws_s3_bucket_notification.documents.queue
        ).events,
        "s3:ObjectCreated:*",
      )
    )
    error_message = "The notification must cover all S3 object-created event variants."
  }

  assert {
    condition = (
      one(
        aws_s3_bucket_notification.documents.queue
      ).filter_prefix ==
      "documents/"
    )
    error_message = "The notification must filter objects by the documents prefix."
  }

  assert {
    condition = (
      one(
        aws_s3_bucket_notification.documents.queue
      ).filter_suffix ==
      "source.txt"
    )
    error_message = "The notification must filter objects by the canonical source filename."
  }

  assert {
    condition = (
      output.documents_bucket_name ==
      aws_s3_bucket.documents.bucket
    )
    error_message = "The documents bucket name output must reference the documents bucket."
  }

  assert {
    condition = (
      output.documents_bucket_arn ==
      aws_s3_bucket.documents.arn
    )
    error_message = "The documents bucket ARN output must reference the documents bucket."
  }
}

run "environment_scoped_document_bucket_name" {
  command = plan

  variables {
    environment = "staging"
  }

  assert {
    condition = (
      local.documents_bucket_name ==
      "clouddoc-staging-123456789012-documents"
    )
    error_message = "Changing the environment must change the documents bucket name."
  }

  assert {
    condition = (
      aws_s3_bucket.documents.bucket ==
      "clouddoc-staging-123456789012-documents"
    )
    error_message = "The S3 resource must use the environment-scoped bucket name."
  }

  assert {
    condition = (
      aws_s3_bucket.documents.tags["Name"] ==
      "clouddoc-staging-123456789012-documents"
    )
    error_message = "The documents bucket Name tag must change with the environment."
  }

  assert {
    condition = (
      local.common_tags["Environment"] ==
      "staging"
    )
    error_message = "Shared infrastructure tags must reflect the selected environment."
  }
}