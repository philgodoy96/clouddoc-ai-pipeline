"""Runtime dependency composition for CloudDoc application services."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import boto3
from botocore.config import Config

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
from clouddoc.observability import (
    NullOperationalLogger,
    OperationalLogger,
)
from clouddoc.providers import (
    AIProvider,
    BedrockAIProvider,
    MockAIProvider,
)
from clouddoc.repositories import (
    DocumentJobRepository,
    DynamoDBDocumentJobRepository,
)
from clouddoc.runtime.settings import (
    BEDROCK_MODEL_ID_ENV_VAR,
    SUPPORTED_AI_PROVIDERS,
    RuntimeConfigurationError,
    RuntimeSettings,
)

_NULL_OPERATIONAL_LOGGER = NullOperationalLogger()

DynamoDBResourceFactory = Callable[..., Any]
S3ClientFactory = Callable[..., Any]
BedrockRuntimeClientFactory = Callable[..., Any]
AIProviderFactory = Callable[[], AIProvider]

BEDROCK_CONNECT_TIMEOUT_SECONDS = 3
BEDROCK_READ_TIMEOUT_SECONDS = 40
BEDROCK_TOTAL_MAX_ATTEMPTS = 2
BEDROCK_RETRY_MODE = "standard"


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


def build_ai_provider(
    *,
    settings: RuntimeSettings,
    bedrock_client_factory: BedrockRuntimeClientFactory = boto3.client,
    operational_logger: OperationalLogger = _NULL_OPERATIONAL_LOGGER,
) -> AIProvider:
    """Build the configured AI provider for document extraction."""
    if settings.ai_provider == "mock":
        return MockAIProvider()

    if settings.ai_provider == "bedrock":
        model_id = settings.bedrock_model_id
        if model_id is None or not model_id.strip():
            raise RuntimeConfigurationError(
                f"missing required environment variable: {BEDROCK_MODEL_ID_ENV_VAR}"
            )

        client_config = Config(
            connect_timeout=BEDROCK_CONNECT_TIMEOUT_SECONDS,
            read_timeout=BEDROCK_READ_TIMEOUT_SECONDS,
            retries={
                "mode": BEDROCK_RETRY_MODE,
                "total_max_attempts": BEDROCK_TOTAL_MAX_ATTEMPTS,
            },
        )
        bedrock_client = bedrock_client_factory(
            "bedrock-runtime",
            config=client_config,
        )

        return BedrockAIProvider(
            client=bedrock_client,
            model_id=settings.bedrock_model_id,
            max_output_tokens=settings.bedrock_max_output_tokens,
            temperature=settings.bedrock_temperature,
            logger=operational_logger,
        )

    supported_providers = ", ".join(sorted(SUPPORTED_AI_PROVIDERS))
    raise RuntimeConfigurationError(
        f"CLOUDDOC_AI_PROVIDER must be one of: {supported_providers}"
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
    ai_provider_factory: AIProviderFactory | None = None,
    bedrock_client_factory: BedrockRuntimeClientFactory = boto3.client,
    operational_logger: OperationalLogger = _NULL_OPERATIONAL_LOGGER,
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
    if ai_provider_factory is not None:
        ai_provider = ai_provider_factory()
    else:
        ai_provider = build_ai_provider(
            settings=settings,
            bedrock_client_factory=bedrock_client_factory,
            operational_logger=operational_logger,
        )
    workflow = ProcessUploadedDocument(
        start_processing=start_processing,
        document_loader=document_loader,
        ai_provider=ai_provider,
        repository=repository,
        clock=clock,
    )

    return ApplicationUploadedDocumentProcessor(
        workflow=workflow,
        logger=operational_logger,
    )


def build_dead_lettered_document_processor(
    *,
    settings: RuntimeSettings,
    dynamodb_resource_factory: DynamoDBResourceFactory = boto3.resource,
    operational_logger: OperationalLogger = _NULL_OPERATIONAL_LOGGER,
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
        logger=operational_logger,
    )
