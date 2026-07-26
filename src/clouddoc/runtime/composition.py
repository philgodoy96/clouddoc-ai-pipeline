"""Runtime dependency composition for CloudDoc application services."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import boto3

from clouddoc.application import (
    CreateDocumentJob,
    DocumentTextLoader,
    GetDocumentJob,
    ProcessUploadedDocument,
    ReconcileDeadLetteredDocument,
    StartDocumentProcessing,
)
from clouddoc.application.dead_letter_processing_ports import (
    DeadLetteredDocumentProcessor,
)
from clouddoc.application.processing_ports import UploadedDocumentProcessor
from clouddoc.application.upload_ports import DocumentUploadProvider
from clouddoc.infrastructure import (
    ApplicationDeadLetteredDocumentProcessor,
    ApplicationUploadedDocumentProcessor,
    S3DocumentTextLoader,
    S3PresignedDocumentUploadProvider,
    SystemClock,
    UUIDJobIdGenerator,
    UUIDProcessingAttemptIdGenerator,
)
from clouddoc.providers import (
    AIProvider,
    MockAIProvider,
)
from clouddoc.repositories import (
    DocumentJobRepository,
    DynamoDBDocumentJobRepository,
)
from clouddoc.runtime.settings import RuntimeSettings

DynamoDBResourceFactory = Callable[..., Any]
S3ClientFactory = Callable[..., Any]
AIProviderFactory = Callable[[], AIProvider]


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


def build_document_text_loader(
    *,
    settings: RuntimeSettings,
    s3_client_factory: S3ClientFactory = boto3.client,
) -> DocumentTextLoader:
    """Build the configured bounded S3 document text loader."""
    s3_client = s3_client_factory("s3")

    return S3DocumentTextLoader(
        s3_client=s3_client,
        bucket_name=settings.documents_bucket_name,
        max_size_bytes=settings.max_document_size_bytes,
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
    s3_client_factory: S3ClientFactory = boto3.client,
    ai_provider_factory: AIProviderFactory = MockAIProvider,
) -> UploadedDocumentProcessor:
    """Build the uploaded-document processor."""
    repository = build_document_job_repository(
        settings=settings,
        dynamodb_resource_factory=dynamodb_resource_factory,
    )
    clock = SystemClock()
    start_processing = StartDocumentProcessing(
        repository=repository,
        clock=clock,
        attempt_id_generator=UUIDProcessingAttemptIdGenerator(),
        lease_duration=timedelta(
            seconds=settings.processing_lease_duration_seconds,
        ),
    )
    document_loader = build_document_text_loader(
        settings=settings,
        s3_client_factory=s3_client_factory,
    )
    ai_provider = ai_provider_factory()
    workflow = ProcessUploadedDocument(
        start_processing=start_processing,
        document_loader=document_loader,
        ai_provider=ai_provider,
        repository=repository,
        clock=clock,
    )

    return ApplicationUploadedDocumentProcessor(
        workflow=workflow,
    )


def build_dead_lettered_document_processor(
    *,
    settings: RuntimeSettings,
    dynamodb_resource_factory: DynamoDBResourceFactory = boto3.resource,
) -> DeadLetteredDocumentProcessor:
    """Build the dead-lettered document reconciliation processor."""
    repository = build_document_job_repository(
        settings=settings,
        dynamodb_resource_factory=dynamodb_resource_factory,
    )
    clock = SystemClock()
    workflow = ReconcileDeadLetteredDocument(
        repository=repository,
        clock=clock,
    )

    return ApplicationDeadLetteredDocumentProcessor(
        workflow=workflow,
    )
