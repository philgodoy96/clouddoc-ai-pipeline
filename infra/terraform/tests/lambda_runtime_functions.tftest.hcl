mock_provider "aws" {
  override_during = plan

  # mock_provider invents a random string for computed .json; IAM resources
  # validate policy JSON, so supply a minimal valid rendered document.
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
  target          = aws_dynamodb_table.document_jobs
  override_during = plan

  values = {
    id  = "clouddoc-dev-document-jobs"
    arn = "arn:aws:dynamodb:us-east-1:123456789012:table/clouddoc-dev-document-jobs"
  }
}

override_resource {
  target          = aws_iam_role.create_job
  override_during = plan

  values = {
    arn = "arn:aws:iam::123456789012:role/clouddoc-dev-create-job-role"
  }
}

override_resource {
  target          = aws_iam_role.get_job
  override_during = plan

  values = {
    arn = "arn:aws:iam::123456789012:role/clouddoc-dev-get-job-role"
  }
}

override_resource {
  target          = aws_iam_role.processor
  override_during = plan

  values = {
    arn = "arn:aws:iam::123456789012:role/clouddoc-dev-process-document-role"
  }
}

override_resource {
  target          = aws_iam_role.dead_letter_reconciler
  override_during = plan

  values = {
    arn = "arn:aws:iam::123456789012:role/clouddoc-dev-reconcile-dead-letter-role"
  }
}

override_resource {
  target          = aws_lambda_function.create_job
  override_during = plan

  values = {
    arn = "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-create-job"
  }
}

override_resource {
  target          = aws_lambda_function.get_job
  override_during = plan

  values = {
    arn = "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-get-job"
  }
}

override_resource {
  target          = aws_lambda_function.processor
  override_during = plan

  values = {
    arn = "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-process-document"
  }
}

override_resource {
  target          = aws_lambda_function.dead_letter_reconciler
  override_during = plan

  values = {
    arn = "arn:aws:lambda:us-east-1:123456789012:function:clouddoc-dev-reconcile-dead-letter"
  }
}

run "lambda_runtime_topology" {
  command = plan

  assert {
    condition = alltrue([
      for function in [
        {
          actual      = aws_lambda_function.create_job
          name        = "clouddoc-dev-create-job"
          handler     = "clouddoc.handlers.create_job.lambda_handler"
          memory      = 256
          timeout     = 10
          environment = local.lambda_runtime_environment
        },
        {
          actual      = aws_lambda_function.get_job
          name        = "clouddoc-dev-get-job"
          handler     = "clouddoc.handlers.get_job.lambda_handler"
          memory      = 256
          timeout     = 5
          environment = local.lambda_runtime_environment
        },
        {
          actual      = aws_lambda_function.processor
          name        = "clouddoc-dev-process-document"
          handler     = "clouddoc.handlers.process_uploaded_document.lambda_handler"
          memory      = 1024
          timeout     = 120
          environment = local.processor_runtime_environment
        },
        {
          actual      = aws_lambda_function.dead_letter_reconciler
          name        = "clouddoc-dev-reconcile-dead-letter"
          handler     = "clouddoc.handlers.reconcile_dead_lettered_document.lambda_handler"
          memory      = 512
          timeout     = 30
          environment = local.lambda_runtime_environment
        },
        ] : (
        function.actual.function_name == function.name &&
        function.actual.handler == function.handler &&
        function.actual.memory_size == function.memory &&
        function.actual.timeout == function.timeout &&
        function.actual.runtime == "python3.12" &&
        function.actual.package_type == "Zip" &&
        function.actual.publish == false &&
        toset(function.actual.architectures) == toset(["x86_64"]) &&
        function.actual.filename == local.lambda_artifact_path &&
        function.actual.source_code_hash == local.lambda_source_code_hash &&
        one(function.actual.environment).variables == function.environment &&
        one(function.actual.logging_config).log_format == "JSON"
      )
    ])
    error_message = "Every Lambda function must match the approved runtime, handler, package, memory, timeout, function-specific environment, and logging contract."
  }

  assert {
    condition = (
      length(keys(local.lambda_runtime_environment)) == 5 &&
      local.lambda_runtime_environment["CLOUDDOC_JOBS_TABLE_NAME"] ==
      aws_dynamodb_table.document_jobs.name &&
      local.lambda_runtime_environment["CLOUDDOC_DOCUMENTS_BUCKET_NAME"] ==
      aws_s3_bucket.documents.bucket &&
      local.lambda_runtime_environment["CLOUDDOC_UPLOAD_URL_EXPIRATION_SECONDS"] ==
      "900" &&
      local.lambda_runtime_environment["CLOUDDOC_PROCESSING_LEASE_DURATION_SECONDS"] ==
      "300" &&
      local.lambda_runtime_environment["CLOUDDOC_MAX_DOCUMENT_SIZE_BYTES"] ==
      "65536"
    )
    error_message = "The shared Lambda environment must contain exactly the five validated application settings."
  }

  assert {
    condition = (
      aws_lambda_function.create_job.role ==
      aws_iam_role.create_job.arn &&
      aws_lambda_function.get_job.role ==
      aws_iam_role.get_job.arn &&
      aws_lambda_function.processor.role ==
      aws_iam_role.processor.arn &&
      aws_lambda_function.dead_letter_reconciler.role ==
      aws_iam_role.dead_letter_reconciler.arn
    )
    error_message = "Each Lambda function must use its dedicated execution role."
  }

  assert {
    condition = alltrue([
      for log_group in [
        {
          actual = aws_cloudwatch_log_group.create_job
          name   = "/aws/lambda/clouddoc-dev-create-job"
        },
        {
          actual = aws_cloudwatch_log_group.get_job
          name   = "/aws/lambda/clouddoc-dev-get-job"
        },
        {
          actual = aws_cloudwatch_log_group.processor
          name   = "/aws/lambda/clouddoc-dev-process-document"
        },
        {
          actual = aws_cloudwatch_log_group.dead_letter_reconciler
          name   = "/aws/lambda/clouddoc-dev-reconcile-dead-letter"
        },
        ] : (
        log_group.actual.name == log_group.name &&
        log_group.actual.retention_in_days == 14
      )
    ])
    error_message = "Development Lambda log groups must use canonical names and fourteen-day retention."
  }

  assert {
    condition = (
      output.create_job_function_name ==
      aws_lambda_function.create_job.function_name &&
      output.create_job_function_arn ==
      aws_lambda_function.create_job.arn &&
      output.get_job_function_name ==
      aws_lambda_function.get_job.function_name &&
      output.get_job_function_arn ==
      aws_lambda_function.get_job.arn &&
      output.processor_function_name ==
      aws_lambda_function.processor.function_name &&
      output.processor_function_arn ==
      aws_lambda_function.processor.arn &&
      output.dead_letter_reconciler_function_name ==
      aws_lambda_function.dead_letter_reconciler.function_name &&
      output.dead_letter_reconciler_function_arn ==
      aws_lambda_function.dead_letter_reconciler.arn
    )
    error_message = "Lambda outputs must reference the declared runtime functions."
  }
}

run "lambda_identity_and_permission_boundaries" {
  command = plan

  assert {
    condition = (
      length(data.aws_iam_policy_document.lambda_assume_role.statement) == 1 &&
      one(
        data.aws_iam_policy_document.lambda_assume_role.statement
      ).effect == "Allow" &&
      toset(
        one(
          data.aws_iam_policy_document.lambda_assume_role.statement
        ).actions
      ) == toset(["sts:AssumeRole"]) &&
      one(
        one(
          data.aws_iam_policy_document.lambda_assume_role.statement
        ).principals
      ).type == "Service" &&
      toset(
        one(
          one(
            data.aws_iam_policy_document.lambda_assume_role.statement
          ).principals
        ).identifiers
      ) == toset(["lambda.amazonaws.com"])
    )
    error_message = "The execution-role trust policy must allow only the Lambda service to assume roles."
  }

  assert {
    condition = (
      length(toset([
        aws_iam_role.create_job.name,
        aws_iam_role.get_job.name,
        aws_iam_role.processor.name,
        aws_iam_role.dead_letter_reconciler.name,
      ])) == 4
    )
    error_message = "Every Lambda function must have an independent execution role."
  }

  assert {
    condition = alltrue([
      for statement in [
        one(data.aws_iam_policy_document.create_job_logging.statement),
        one(data.aws_iam_policy_document.get_job_logging.statement),
        one(data.aws_iam_policy_document.processor_logging.statement),
        one(data.aws_iam_policy_document.dead_letter_reconciler_logging.statement),
        ] : (
        toset(statement.actions) ==
        toset([
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]) &&
        length(statement.resources) == 1
      )
    ])
    error_message = "Logging policies must grant only log-stream creation and event writes against one resource boundary."
  }

  assert {
    condition = (
      toset(
        one([
          for statement in data.aws_iam_policy_document.create_job_permissions.statement :
          statement if statement.sid == "CreateDocumentJob"
        ]).actions
      ) == toset(["dynamodb:PutItem"]) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.create_job_permissions.statement :
          statement if statement.sid == "CreateDocumentJob"
        ]).resources
      ) == toset([aws_dynamodb_table.document_jobs.arn])
    )
    error_message = "Create Job must receive only PutItem against the authoritative jobs table."
  }

  assert {
    condition = (
      toset(
        one([
          for statement in data.aws_iam_policy_document.create_job_permissions.statement :
          statement if statement.sid == "AuthorizeCanonicalDocumentUpload"
        ]).actions
      ) == toset(["s3:PutObject"]) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.create_job_permissions.statement :
          statement if statement.sid == "AuthorizeCanonicalDocumentUpload"
        ]).resources
      ) == toset(["${aws_s3_bucket.documents.arn}/documents/*"])
    )
    error_message = "Create Job must authorize only canonical-prefix S3 uploads."
  }

  assert {
    condition = (
      toset(
        one(
          data.aws_iam_policy_document.get_job_permissions.statement
        ).actions
      ) == toset(["dynamodb:GetItem"]) &&
      toset(
        one(
          data.aws_iam_policy_document.get_job_permissions.statement
        ).resources
      ) == toset([aws_dynamodb_table.document_jobs.arn])
    )
    error_message = "Get Job must receive only GetItem against the authoritative jobs table."
  }

  assert {
    condition = (
      toset(
        one([
          for statement in data.aws_iam_policy_document.processor_permissions.statement :
          statement if statement.sid == "ReadAndPersistDocumentJob"
        ]).actions
        ) == toset([
          "dynamodb:GetItem",
          "dynamodb:PutItem",
      ]) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.processor_permissions.statement :
          statement if statement.sid == "ReadAndPersistDocumentJob"
        ]).resources
      ) == toset([aws_dynamodb_table.document_jobs.arn])
    )
    error_message = "The Processor must receive only GetItem and PutItem against the jobs table."
  }

  assert {
    condition = (
      toset(
        one([
          for statement in data.aws_iam_policy_document.processor_permissions.statement :
          statement if statement.sid == "ReadCanonicalDocumentObject"
        ]).actions
        ) == toset([
          "s3:GetObject",
          "s3:GetObjectVersion",
      ]) &&
      toset(
        one([
          for statement in data.aws_iam_policy_document.processor_permissions.statement :
          statement if statement.sid == "ReadCanonicalDocumentObject"
        ]).resources
      ) == toset(["${aws_s3_bucket.documents.arn}/documents/*"])
    )
    error_message = "The Processor must receive only canonical-prefix S3 read permissions."
  }

  assert {
    condition = (
      toset(
        one(
          data.aws_iam_policy_document
          .dead_letter_reconciler_permissions.statement
        ).actions
        ) == toset([
          "dynamodb:GetItem",
          "dynamodb:PutItem",
      ]) &&
      toset(
        one(
          data.aws_iam_policy_document
          .dead_letter_reconciler_permissions.statement
        ).resources
      ) == toset([aws_dynamodb_table.document_jobs.arn])
    )
    error_message = "The Dead-Letter Reconciler must receive only GetItem and PutItem against the jobs table."
  }

  assert {
    condition = (
      length([
        for action in flatten([
          flatten([
            for statement in data.aws_iam_policy_document.create_job_permissions.statement :
            statement.actions
          ]),
          flatten([
            for statement in data.aws_iam_policy_document.get_job_permissions.statement :
            statement.actions
          ]),
          flatten([
            for statement in data.aws_iam_policy_document.processor_permissions.statement :
            statement.actions
          ]),
          flatten([
            for statement in data.aws_iam_policy_document.dead_letter_reconciler_permissions.statement :
            statement.actions
          ]),
        ]) : action
        if startswith(action, "sqs:") || startswith(action, "bedrock:")
      ]) == 0
    )
    error_message = "Runtime business policies must not grant SQS or Bedrock permissions in this slice."
  }
}

run "production_lambda_boundaries" {
  command = plan

  variables {
    environment = "prod"
  }

  assert {
    condition = (
      local.create_job_function_name == "clouddoc-prod-create-job" &&
      local.get_job_function_name == "clouddoc-prod-get-job" &&
      local.processor_function_name == "clouddoc-prod-process-document" &&
      local.dead_letter_reconciler_function_name ==
      "clouddoc-prod-reconcile-dead-letter"
    )
    error_message = "Production Lambda names must be environment-scoped."
  }

  assert {
    condition = (
      local.lambda_log_retention_days == 30 &&
      aws_cloudwatch_log_group.create_job.retention_in_days == 30 &&
      aws_cloudwatch_log_group.get_job.retention_in_days == 30 &&
      aws_cloudwatch_log_group.processor.retention_in_days == 30 &&
      aws_cloudwatch_log_group.dead_letter_reconciler.retention_in_days == 30
    )
    error_message = "Production Lambda logs must be retained for thirty days."
  }
}