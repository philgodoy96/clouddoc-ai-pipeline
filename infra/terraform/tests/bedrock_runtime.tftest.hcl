mock_provider "aws" {
  override_during = plan

  # IAM policy resources require valid rendered JSON during mocked plans.
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

override_data {
  target          = data.aws_partition.current
  override_during = plan

  values = {
    partition = "aws"
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
    id   = "clouddoc-dev-document-jobs"
    name = "clouddoc-dev-document-jobs"
    arn  = "arn:aws:dynamodb:us-east-1:123456789012:table/clouddoc-dev-document-jobs"
  }
}

override_resource {
  target          = aws_iam_role.processor
  override_during = plan

  values = {
    id  = "clouddoc-dev-process-document-role"
    arn = "arn:aws:iam::123456789012:role/clouddoc-dev-process-document-role"
  }
}

run "bedrock_processor_runtime_configuration" {
  command = plan

  assert {
    condition = (
      length(keys(local.lambda_runtime_environment)) == 5 &&
      length(keys(local.processor_runtime_environment)) == 9
    )
    error_message = "The Processor environment must extend the five shared settings with exactly four Bedrock settings."
  }

  assert {
    condition = (
      local.processor_runtime_environment["CLOUDDOC_AI_PROVIDER"] == "bedrock" &&
      local.processor_runtime_environment["CLOUDDOC_BEDROCK_MODEL_ID"] ==
      "amazon.nova-micro-v1:0" &&
      local.processor_runtime_environment["CLOUDDOC_BEDROCK_MAX_OUTPUT_TOKENS"] ==
      "1200" &&
      local.processor_runtime_environment["CLOUDDOC_BEDROCK_TEMPERATURE"] ==
      "0.00001"
    )
    error_message = "The Processor must receive the approved Bedrock provider and bounded Nova Micro inference configuration."
  }

  assert {
    condition = (
      one(aws_lambda_function.processor.environment).variables ==
      local.processor_runtime_environment
    )
    error_message = "The Processor Lambda must receive the Processor-specific runtime environment."
  }

  assert {
    condition = alltrue([
      for runtime_environment in [
        one(aws_lambda_function.create_job.environment).variables,
        one(aws_lambda_function.get_job.environment).variables,
        one(aws_lambda_function.dead_letter_reconciler.environment).variables,
        ] : (
        runtime_environment == local.lambda_runtime_environment &&
        !contains(keys(runtime_environment), "CLOUDDOC_AI_PROVIDER") &&
        !contains(keys(runtime_environment), "CLOUDDOC_BEDROCK_MODEL_ID") &&
        !contains(
          keys(runtime_environment),
          "CLOUDDOC_BEDROCK_MAX_OUTPUT_TOKENS",
        ) &&
        !contains(keys(runtime_environment), "CLOUDDOC_BEDROCK_TEMPERATURE")
      )
    ])
    error_message = "Non-Processor Lambdas must retain only the shared runtime environment and receive no Bedrock configuration."
  }
}

run "bedrock_processor_model_permissions" {
  command = plan

  assert {
    condition = (
      local.bedrock_foundation_model_arn ==
      "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-micro-v1:0"
    )
    error_message = "The configured Bedrock model ARN must be partition-aware, regional, accountless, and exact."
  }

  assert {
    condition = (
      length(
        data.aws_iam_policy_document.processor_bedrock_invoke.statement
      ) == 1 &&
      one(
        data.aws_iam_policy_document.processor_bedrock_invoke.statement
      ).sid == "InvokeConfiguredFoundationModel" &&
      one(
        data.aws_iam_policy_document.processor_bedrock_invoke.statement
      ).effect == "Allow" &&
      toset(
        one(
          data.aws_iam_policy_document.processor_bedrock_invoke.statement
        ).actions
      ) == toset(["bedrock:InvokeModel"]) &&
      toset(
        one(
          data.aws_iam_policy_document.processor_bedrock_invoke.statement
        ).resources
      ) == toset([local.bedrock_foundation_model_arn])
    )
    error_message = "The Processor Bedrock policy must grant only InvokeModel against the exact configured foundation-model ARN."
  }

  assert {
    condition = (
      aws_iam_role_policy.processor_bedrock_invoke.name ==
      "clouddoc-dev-process-document-bedrock-invoke" &&
      aws_iam_role_policy.processor_bedrock_invoke.role ==
      aws_iam_role.processor.id
    )
    error_message = "The dedicated Bedrock invocation policy must attach only to the Processor execution role."
  }
}

run "bedrock_runtime_isolation" {
  command = plan

  assert {
    condition = (
      !contains(
        toset(
          one(
            data.aws_iam_policy_document.processor_bedrock_invoke.statement
          ).actions
        ),
        "bedrock:InvokeModelWithResponseStream",
      ) &&
      !contains(
        toset(
          one(
            data.aws_iam_policy_document.processor_bedrock_invoke.statement
          ).actions
        ),
        "bedrock:*",
      ) &&
      !contains(
        toset(
          one(
            data.aws_iam_policy_document.processor_bedrock_invoke.statement
          ).resources
        ),
        "*",
      )
    )
    error_message = "The Bedrock boundary must contain no streaming, action wildcard, or resource wildcard permission."
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
        if startswith(action, "bedrock:")
      ]) == 0
    )
    error_message = "Existing runtime business policies must remain free of Bedrock permissions; invocation belongs only to the dedicated Processor policy."
  }

  assert {
    condition = alltrue([
      for runtime_environment in [
        one(aws_lambda_function.create_job.environment).variables,
        one(aws_lambda_function.get_job.environment).variables,
        one(aws_lambda_function.dead_letter_reconciler.environment).variables,
        ] : length([
          for key in keys(runtime_environment) : key
          if startswith(key, "CLOUDDOC_BEDROCK_") ||
          key == "CLOUDDOC_AI_PROVIDER"
      ]) == 0
    ])
    error_message = "Bedrock runtime configuration must remain isolated from Create Job, Get Job, and Dead-Letter Reconciler."
  }
}
