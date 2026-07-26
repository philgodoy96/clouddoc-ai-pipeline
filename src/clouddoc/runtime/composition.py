"""Runtime dependency composition for CloudDoc application services."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import boto3

from clouddoc.application import (
    CreateDocumentJob,
    GetDocumentJob,
    StartDocumentProcessing,
)
from clouddoc.application.processing_ports import UploadedDocumentProcessor
from clouddoc.application.upload_ports import DocumentUploadProvider
from clouddoc.infrastructure import (
    ApplicationUploadedDocumentProcessor,
    S3PresignedDocumentUploadProvider,
    SystemClock,
    UUIDJobIdGenerator,
    UUIDProcessingAttemptIdGenerator,
)
from clouddoc.repositories import (
    DocumentJobRepository,
    DynamoDBDocumentJobRepository,
)
from clouddoc.runtime.settings import RuntimeSettings

DynamoDBResourceFactory = Callable[..., Any]
S3ClientFactory = Callable[..., Any]


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


def build_document_upload_provider(
    *,
    settings: RuntimeSettings,
    s3_client_factory: S3ClientFactory = boto3.client,
) -> DocumentUploadProvider:
    """Build the configured S3 document upload provider."""
    s3_client = s3_client_factory("s3")

    return S3PresignedDocumentUploadProvider(
        s3_client=s3_client,
        bucket_name=settings.documents_bucket_name,
        expiration_seconds=settings.upload_url_expiration_seconds,
    )


def build_create_document_job_service(
    *,
    settings: RuntimeSettings,
    dynamodb_resource_factory: DynamoDBResourceFactory = boto3.resource,
    s3_client_factory: S3ClientFactory = boto3.client,
) -> CreateDocumentJob:
    """Build the document-job creation application service."""
    repository = build_document_job_repository(
        settings=settings,
        dynamodb_resource_factory=dynamodb_resource_factory,
    )
    upload_provider = build_document_upload_provider(
        settings=settings,
        s3_client_factory=s3_client_factory,
    )

    return CreateDocumentJob(
        repository=repository,
        clock=SystemClock(),
        job_id_generator=UUIDJobIdGenerator(),
        upload_provider=upload_provider,
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


def build_uploaded_document_processor(
    *,
    settings: RuntimeSettings,
    dynamodb_resource_factory: DynamoDBResourceFactory = boto3.resource,
) -> UploadedDocumentProcessor:
    """Build the uploaded-document processor."""
    repository = build_document_job_repository(
        settings=settings,
        dynamodb_resource_factory=dynamodb_resource_factory,
    )
    service = StartDocumentProcessing(
        repository=repository,
        clock=SystemClock(),
        attempt_id_generator=UUIDProcessingAttemptIdGenerator(),
        lease_duration=timedelta(
            seconds=settings.processing_lease_duration_seconds,
        ),
    )

    return ApplicationUploadedDocumentProcessor(
        service=service,
    )
