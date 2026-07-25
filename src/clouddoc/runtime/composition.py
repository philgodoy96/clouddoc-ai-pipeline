"""Runtime dependency composition for CloudDoc application services."""

from collections.abc import Callable
from typing import Any

import boto3

from clouddoc.application import (
    CreateDocumentJob,
    GetDocumentJob,
)
from clouddoc.infrastructure import (
    SystemClock,
    UUIDJobIdGenerator,
)
from clouddoc.repositories import (
    DocumentJobRepository,
    DynamoDBDocumentJobRepository,
)
from clouddoc.runtime.settings import RuntimeSettings

DynamoDBResourceFactory = Callable[..., Any]


def build_document_job_repository(
    *,
    settings: RuntimeSettings,
    dynamodb_resource_factory: DynamoDBResourceFactory = boto3.resource,
) -> DocumentJobRepository:
    """Build the configured DynamoDB document-job repository."""
    dynamodb = dynamodb_resource_factory("dynamodb")
    table = dynamodb.Table(settings.jobs_table_name)

    return DynamoDBDocumentJobRepository(
        table=table,
    )


def build_create_document_job_service(
    *,
    settings: RuntimeSettings,
    dynamodb_resource_factory: DynamoDBResourceFactory = boto3.resource,
) -> CreateDocumentJob:
    """Build the document-job creation application service."""
    repository = build_document_job_repository(
        settings=settings,
        dynamodb_resource_factory=dynamodb_resource_factory,
    )

    return CreateDocumentJob(
        repository=repository,
        clock=SystemClock(),
        job_id_generator=UUIDJobIdGenerator(),
    )


def build_get_document_job_service(
    *,
    settings: RuntimeSettings,
    dynamodb_resource_factory: DynamoDBResourceFactory = boto3.resource,
) -> GetDocumentJob:
    """Build the document-job query application service."""
    repository = build_document_job_repository(
        settings=settings,
        dynamodb_resource_factory=dynamodb_resource_factory,
    )

    return GetDocumentJob(
        repository=repository,
    )
