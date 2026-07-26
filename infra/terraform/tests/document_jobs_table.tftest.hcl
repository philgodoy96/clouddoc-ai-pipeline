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
  target          = aws_dynamodb_table.document_jobs
  override_during = plan

  values = {
    id  = "clouddoc-dev-document-jobs"
    arn = "arn:aws:dynamodb:us-east-1:123456789012:table/clouddoc-dev-document-jobs"
  }
}

run "development_document_jobs_table" {
  command = plan

  assert {
    condition = (
      local.document_jobs_table_name ==
      "clouddoc-dev-document-jobs"
    )
    error_message = "The development document-jobs table name must be environment-scoped."
  }

  assert {
    condition     = local.is_production == false
    error_message = "The development environment must not be treated as production."
  }

  assert {
    condition = (
      aws_dynamodb_table.document_jobs.name ==
      local.document_jobs_table_name
    )
    error_message = "The DynamoDB table must use the approved document-jobs table name."
  }

  assert {
    condition = (
      aws_dynamodb_table.document_jobs.billing_mode ==
      "PAY_PER_REQUEST"
    )
    error_message = "The document-jobs table must use on-demand capacity."
  }

  assert {
    condition = (
      aws_dynamodb_table.document_jobs.hash_key ==
      "PK"
    )
    error_message = "The document-jobs table partition key must be PK."
  }

  assert {
    condition = (
      aws_dynamodb_table.document_jobs.range_key ==
      null
    )
    error_message = "The document-jobs table must not define a sort key."
  }

  assert {
    condition = (
      length(
        aws_dynamodb_table.document_jobs.attribute
      ) ==
      1
    )
    error_message = "The document-jobs table must declare exactly one key attribute."
  }

  assert {
    condition = (
      one(
        aws_dynamodb_table.document_jobs.attribute
      ).name ==
      "PK"
    )
    error_message = "The declared DynamoDB key attribute must be PK."
  }

  assert {
    condition = (
      one(
        aws_dynamodb_table.document_jobs.attribute
      ).type ==
      "S"
    )
    error_message = "The PK attribute must use the DynamoDB string type."
  }

  assert {
    condition = (
      aws_dynamodb_table.document_jobs.table_class ==
      "STANDARD"
    )
    error_message = "The document-jobs table must use the STANDARD table class."
  }

  assert {
    condition = (
      one(
        aws_dynamodb_table.document_jobs
        .point_in_time_recovery
      ).enabled
    )
    error_message = "Point-in-time recovery must be enabled."
  }

  assert {
    condition = (
      aws_dynamodb_table.document_jobs
      .deletion_protection_enabled ==
      false
    )
    error_message = "Development deletion protection must remain disabled."
  }

  assert {
    condition = (
      aws_dynamodb_table.document_jobs.stream_enabled ==
      false
    )
    error_message = "DynamoDB Streams must remain disabled."
  }

  assert {
    condition = (
      length(
        aws_dynamodb_table.document_jobs.ttl
      ) ==
      0
    )
    error_message = "The document-jobs table must not configure TTL."
  }

  assert {
    condition = (
      length(
        aws_dynamodb_table.document_jobs
        .global_secondary_index
      ) ==
      0
    )
    error_message = "The document-jobs table must not define global secondary indexes."
  }

  assert {
    condition = (
      length(
        aws_dynamodb_table.document_jobs
        .local_secondary_index
      ) ==
      0
    )
    error_message = "The document-jobs table must not define local secondary indexes."
  }

  assert {
    condition = (
      length(
        aws_dynamodb_table.document_jobs
        .server_side_encryption
      ) ==
      0
    )
    error_message = "The table must use DynamoDB default encryption rather than a custom KMS configuration."
  }

  assert {
    condition = (
      aws_dynamodb_table.document_jobs.tags["Name"] ==
      local.document_jobs_table_name
    )
    error_message = "The DynamoDB Name tag must match the table name."
  }

  assert {
    condition = (
      aws_dynamodb_table.document_jobs
      .tags["TableRole"] ==
      "authoritative-job-state"
    )
    error_message = "The table must be tagged as authoritative job state."
  }

  assert {
    condition = (
      output.document_jobs_table_name ==
      aws_dynamodb_table.document_jobs.name
    )
    error_message = "The table-name output must reference the document-jobs table."
  }

  assert {
    condition = (
      output.document_jobs_table_arn ==
      aws_dynamodb_table.document_jobs.arn
    )
    error_message = "The table-ARN output must reference the document-jobs table."
  }
}

run "staging_document_jobs_table" {
  command = plan

  variables {
    environment = "staging"
  }

  assert {
    condition = (
      local.document_jobs_table_name ==
      "clouddoc-staging-document-jobs"
    )
    error_message = "The staging document-jobs table name must be environment-scoped."
  }

  assert {
    condition = (
      aws_dynamodb_table.document_jobs.name ==
      "clouddoc-staging-document-jobs"
    )
    error_message = "The DynamoDB resource must use the staging table name."
  }

  assert {
    condition     = local.is_production == false
    error_message = "The staging environment must not be treated as production."
  }

  assert {
    condition = (
      aws_dynamodb_table.document_jobs
      .deletion_protection_enabled ==
      false
    )
    error_message = "Staging deletion protection must remain disabled."
  }

  assert {
    condition = (
      local.common_tags["Environment"] ==
      "staging"
    )
    error_message = "Shared infrastructure tags must identify the staging environment."
  }
}

run "production_document_jobs_table" {
  command = plan

  variables {
    environment = "prod"
  }

  assert {
    condition = (
      local.document_jobs_table_name ==
      "clouddoc-prod-document-jobs"
    )
    error_message = "The production document-jobs table name must be environment-scoped."
  }

  assert {
    condition = (
      aws_dynamodb_table.document_jobs.name ==
      "clouddoc-prod-document-jobs"
    )
    error_message = "The DynamoDB resource must use the production table name."
  }

  assert {
    condition     = local.is_production
    error_message = "The prod environment must be recognized as production."
  }

  assert {
    condition = (
      aws_dynamodb_table.document_jobs
      .deletion_protection_enabled
    )
    error_message = "Production deletion protection must be enabled."
  }

  assert {
    condition = (
      local.common_tags["Environment"] ==
      "prod"
    )
    error_message = "Shared infrastructure tags must identify the production environment."
  }
}