# Terraform Infrastructure

This directory will contain the Terraform configuration for CloudDoc AI Pipeline.

The infrastructure will be introduced incrementally after the application
boundaries, runtime responsibilities, and deployment requirements have been
defined.

## Planned responsibilities

Terraform will manage the AWS resources required by the document-processing
workflow, including:

- API Gateway
- AWS Lambda functions
- Amazon S3 document storage
- Amazon SQS processing and dead-letter queues
- Amazon DynamoDB job state storage
- Amazon CloudWatch log groups and alarms
- IAM roles and least-privilege policies
- event source mappings and service integrations

## Current status

Infrastructure resources have not been implemented yet.

This directory is intentionally limited to documentation during the repository
foundation phase.