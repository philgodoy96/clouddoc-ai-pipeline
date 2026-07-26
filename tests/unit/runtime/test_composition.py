"""Tests for runtime dependency composition."""

from datetime import timedelta
from typing import Any

from clouddoc.application import (
    CreateDocumentJob,
    DocumentTextLoader,
    GetDocumentJob,
    ProcessUploadedDocument,
    StartDocumentProcessing,
)
from clouddoc.application.processing_ports import UploadedDocumentProcessor
from clouddoc.infrastructure import (
    ApplicationUploadedDocumentProcessor,
    S3DocumentTextLoader,
    S3PresignedDocumentUploadProvider,
    SystemClock,
    UUIDJobIdGenerator,
    UUIDProcessingAttemptIdGenerator,
)
from clouddoc.providers import (
    AIProvider,
    AIProviderRequest,
    MockAIProvider,
)
from clouddoc.repositories import (
    DynamoDBDocumentJobRepository,
)
from clouddoc.runtime.composition import (
    build_create_document_job_service,
    build_document_job_repository,
    build_document_text_loader,
    build_document_upload_provider,
    build_get_document_job_service,
    build_uploaded_document_processor,
)
from clouddoc.runtime.settings import RuntimeSettings
from clouddoc.schemas import AIExtractionResult


class FakeDynamoDBTable:
    """Minimal table reference used to inspect runtime composition."""

    def __init__(
        self,
        name: str,
    ) -> None:
        """Store the requested table name."""
        self.name = name


class FakeDynamoDBResource:
    """Minimal DynamoDB resource used by composition tests."""

    def __init__(self) -> None:
        """Initialize resource call tracking."""
        self.requested_table_names: list[str] = []

    def Table(
        self,
        table_name: str,
    ) -> FakeDynamoDBTable:
        """Return a fake table for the requested name."""
        self.requested_table_names.append(table_name)

        return FakeDynamoDBTable(table_name)


class RecordingResourceFactory:
    """Record boto3-style resource construction requests."""

    def __init__(self) -> None:
        """Initialize the fake DynamoDB resource."""
        self.resource = FakeDynamoDBResource()
        self.service_names: list[str] = []

    def __call__(
        self,
        service_name: str,
        *args: object,
        **kwargs: object,
    ) -> FakeDynamoDBResource:
        """Return the fake resource for DynamoDB."""
        self.service_names.append(service_name)

        return self.resource


class FakeS3Client:
    """Minimal S3 client used to inspect runtime composition."""


class RecordingClientFactory:
    """Record boto3-style client construction requests."""

    def __init__(self) -> None:
        """Initialize the fake S3 client."""
        self.client = FakeS3Client()
        self.service_names: list[str] = []

    def __call__(
        self,
        service_name: str,
        *args: object,
        **kwargs: object,
    ) -> FakeS3Client:
        """Return the fake client for S3."""
        self.service_names.append(service_name)

        return self.client


class RecordingAIProvider:
    """Minimal AI provider used to inspect runtime composition."""

    provider_name = "recording"

    def __init__(self) -> None:
        """Initialize request tracking."""
        self.requests: list[AIProviderRequest] = []

    def extract(
        self,
        request: AIProviderRequest,
    ) -> AIExtractionResult:
        """Record the request and refuse execution during composition tests."""
        self.requests.append(request)
        raise AssertionError("composition tests must not invoke the AI provider")


class RecordingAIProviderFactory:
    """Record AI provider factory invocations."""

    def __init__(self) -> None:
        """Own one recording provider instance."""
        self.provider = RecordingAIProvider()
        self.calls = 0

    def __call__(self) -> RecordingAIProvider:
        """Return the owned provider and count the invocation."""
        self.calls += 1
        return self.provider


def make_settings() -> RuntimeSettings:
    """Create valid runtime settings."""
    return RuntimeSettings(
        jobs_table_name="clouddoc-document-jobs",
        documents_bucket_name="clouddoc-documents",
        upload_url_expiration_seconds=900,
        processing_lease_duration_seconds=300,
        max_document_size_bytes=65_536,
    )


def test_builds_repository_with_configured_table() -> None:
    """Composition should target the configured DynamoDB table."""
    resource_factory = RecordingResourceFactory()

    repository = build_document_job_repository(
        settings=make_settings(),
        dynamodb_resource_factory=resource_factory,
    )

    assert isinstance(
        repository,
        DynamoDBDocumentJobRepository,
    )
    assert resource_factory.service_names == [
        "dynamodb",
    ]
    assert resource_factory.resource.requested_table_names == [
        "clouddoc-document-jobs",
    ]


def test_builds_document_job_creation_service() -> None:
    """Composition should build the complete creation use case."""
    resource_factory = RecordingResourceFactory()
    client_factory = RecordingClientFactory()

    service = build_create_document_job_service(
        settings=make_settings(),
        dynamodb_resource_factory=resource_factory,
        s3_client_factory=client_factory,
    )

    assert isinstance(service, CreateDocumentJob)
    assert isinstance(
        service._repository,
        DynamoDBDocumentJobRepository,
    )
    assert isinstance(service._clock, SystemClock)
    assert isinstance(
        service._job_id_generator,
        UUIDJobIdGenerator,
    )
    assert isinstance(
        service._upload_provider,
        S3PresignedDocumentUploadProvider,
    )
    assert resource_factory.service_names == [
        "dynamodb",
    ]
    assert client_factory.service_names == [
        "s3",
    ]


def test_builds_document_job_query_service() -> None:
    """Composition should build the complete query use case."""
    resource_factory = RecordingResourceFactory()

    service = build_get_document_job_service(
        settings=make_settings(),
        dynamodb_resource_factory=resource_factory,
    )

    assert isinstance(service, GetDocumentJob)
    assert isinstance(
        service._repository,
        DynamoDBDocumentJobRepository,
    )


def test_each_service_uses_configured_table_name() -> None:
    """Both application services should use the approved table."""
    creation_factory = RecordingResourceFactory()
    query_factory = RecordingResourceFactory()

    build_create_document_job_service(
        settings=make_settings(),
        dynamodb_resource_factory=creation_factory,
    )
    build_get_document_job_service(
        settings=make_settings(),
        dynamodb_resource_factory=query_factory,
    )

    assert creation_factory.resource.requested_table_names == [
        "clouddoc-document-jobs",
    ]
    assert query_factory.resource.requested_table_names == [
        "clouddoc-document-jobs",
    ]


def test_builds_document_upload_provider() -> None:
    """Composition should return the S3 upload provider implementation."""
    client_factory = RecordingClientFactory()

    provider = build_document_upload_provider(
        settings=make_settings(),
        s3_client_factory=client_factory,
    )

    assert isinstance(
        provider,
        S3PresignedDocumentUploadProvider,
    )
    assert client_factory.service_names == [
        "s3",
    ]
    assert provider._s3_client is client_factory.client
    assert provider._bucket_name == "clouddoc-documents"
    assert provider._expiration_seconds == 900


def test_document_upload_provider_uses_custom_settings() -> None:
    """Composition should propagate custom bucket and expiration settings."""
    client_factory = RecordingClientFactory()
    settings = RuntimeSettings(
        jobs_table_name="clouddoc-document-jobs",
        documents_bucket_name="custom-documents-bucket",
        upload_url_expiration_seconds=600,
        processing_lease_duration_seconds=300,
        max_document_size_bytes=65_536,
    )

    provider = build_document_upload_provider(
        settings=settings,
        s3_client_factory=client_factory,
    )

    assert isinstance(
        provider,
        S3PresignedDocumentUploadProvider,
    )
    assert provider._bucket_name == "custom-documents-bucket"
    assert provider._expiration_seconds == 600
    assert provider._s3_client is client_factory.client


def test_builds_document_text_loader() -> None:
    """Composition should return the bounded S3 document text loader."""
    client_factory = RecordingClientFactory()

    loader = build_document_text_loader(
        settings=make_settings(),
        s3_client_factory=client_factory,
    )

    assert isinstance(loader, S3DocumentTextLoader)
    assert isinstance(loader, DocumentTextLoader)
    assert client_factory.service_names == [
        "s3",
    ]
    assert loader._s3_client is client_factory.client
    assert loader._bucket_name == "clouddoc-documents"
    assert loader._max_size_bytes == 65_536


def test_document_text_loader_uses_custom_settings() -> None:
    """Composition should propagate custom bucket and size-limit settings."""
    client_factory = RecordingClientFactory()
    settings = RuntimeSettings(
        jobs_table_name="clouddoc-document-jobs",
        documents_bucket_name="custom-document-bucket",
        upload_url_expiration_seconds=900,
        processing_lease_duration_seconds=300,
        max_document_size_bytes=131_072,
    )

    loader = build_document_text_loader(
        settings=settings,
        s3_client_factory=client_factory,
    )

    assert isinstance(loader, S3DocumentTextLoader)
    assert isinstance(loader, DocumentTextLoader)
    assert loader._bucket_name == "custom-document-bucket"
    assert loader._max_size_bytes == 131_072
    assert loader._s3_client is client_factory.client


def test_document_text_loader_is_not_cached() -> None:
    """Composition should return a fresh loader on each call."""
    first_factory = RecordingClientFactory()
    second_factory = RecordingClientFactory()

    first = build_document_text_loader(
        settings=make_settings(),
        s3_client_factory=first_factory,
    )
    second = build_document_text_loader(
        settings=make_settings(),
        s3_client_factory=second_factory,
    )

    assert first is not second
    assert first_factory.service_names == [
        "s3",
    ]
    assert second_factory.service_names == [
        "s3",
    ]
    assert first._s3_client is first_factory.client
    assert second._s3_client is second_factory.client


def test_composition_does_not_require_real_aws_access() -> None:
    """Dependency wiring should be testable without network access."""
    resource_factory = RecordingResourceFactory()
    client_factory = RecordingClientFactory()

    services: tuple[Any, ...] = (
        build_create_document_job_service(
            settings=make_settings(),
            dynamodb_resource_factory=resource_factory,
            s3_client_factory=client_factory,
        ),
        build_get_document_job_service(
            settings=make_settings(),
            dynamodb_resource_factory=resource_factory,
        ),
        build_document_upload_provider(
            settings=make_settings(),
            s3_client_factory=client_factory,
        ),
        build_document_text_loader(
            settings=make_settings(),
            s3_client_factory=client_factory,
        ),
        build_uploaded_document_processor(
            settings=make_settings(),
            dynamodb_resource_factory=resource_factory,
            s3_client_factory=client_factory,
        ),
    )

    assert all(services)
    assert resource_factory.service_names == [
        "dynamodb",
        "dynamodb",
        "dynamodb",
    ]
    assert client_factory.service_names == [
        "s3",
        "s3",
        "s3",
        "s3",
    ]


def test_builds_uploaded_document_processor() -> None:
    """Composition should return the authoritative uploaded-document processor."""
    resource_factory = RecordingResourceFactory()
    client_factory = RecordingClientFactory()

    processor = build_uploaded_document_processor(
        settings=make_settings(),
        dynamodb_resource_factory=resource_factory,
        s3_client_factory=client_factory,
    )

    assert isinstance(processor, ApplicationUploadedDocumentProcessor)
    assert isinstance(processor, UploadedDocumentProcessor)

    workflow = processor._workflow
    start_processing = workflow._start_processing
    repository = workflow._repository
    clock = workflow._clock
    document_loader = workflow._document_loader
    ai_provider = workflow._ai_provider

    assert isinstance(workflow, ProcessUploadedDocument)
    assert isinstance(start_processing, StartDocumentProcessing)
    assert isinstance(repository, DynamoDBDocumentJobRepository)
    assert isinstance(clock, SystemClock)
    assert start_processing._repository is repository
    assert start_processing._clock is clock
    assert workflow._repository is repository
    assert workflow._clock is clock
    assert isinstance(
        start_processing._attempt_id_generator,
        UUIDProcessingAttemptIdGenerator,
    )
    assert start_processing._lease_duration == timedelta(seconds=300)
    assert isinstance(document_loader, S3DocumentTextLoader)
    assert isinstance(document_loader, DocumentTextLoader)
    assert document_loader._s3_client is client_factory.client
    assert document_loader._bucket_name == "clouddoc-documents"
    assert document_loader._max_size_bytes == 65_536
    assert isinstance(ai_provider, MockAIProvider)
    assert isinstance(ai_provider, AIProvider)
    assert resource_factory.service_names == [
        "dynamodb",
    ]
    assert client_factory.service_names == [
        "s3",
    ]


def test_uploaded_document_processor_propagates_custom_configuration() -> None:
    """Composition should propagate custom lease, bucket, and size settings."""
    resource_factory = RecordingResourceFactory()
    client_factory = RecordingClientFactory()
    settings = RuntimeSettings(
        jobs_table_name="clouddoc-document-jobs",
        documents_bucket_name="custom-document-bucket",
        upload_url_expiration_seconds=900,
        processing_lease_duration_seconds=600,
        max_document_size_bytes=131_072,
    )

    processor = build_uploaded_document_processor(
        settings=settings,
        dynamodb_resource_factory=resource_factory,
        s3_client_factory=client_factory,
    )

    workflow = processor._workflow

    assert workflow._start_processing._lease_duration == timedelta(seconds=600)
    assert workflow._document_loader._bucket_name == "custom-document-bucket"
    assert workflow._document_loader._max_size_bytes == 131_072
    assert isinstance(workflow._ai_provider, MockAIProvider)
    assert workflow._repository is workflow._start_processing._repository
    assert workflow._clock is workflow._start_processing._clock
    assert isinstance(workflow._clock, SystemClock)


def test_uploaded_document_processor_uses_custom_ai_provider_factory() -> None:
    """Composition should wire the exact provider returned by a custom factory."""
    resource_factory = RecordingResourceFactory()
    client_factory = RecordingClientFactory()
    recording_provider_factory = RecordingAIProviderFactory()

    processor = build_uploaded_document_processor(
        settings=make_settings(),
        dynamodb_resource_factory=resource_factory,
        s3_client_factory=client_factory,
        ai_provider_factory=recording_provider_factory,
    )

    workflow = processor._workflow

    assert recording_provider_factory.calls == 1
    assert workflow._ai_provider is recording_provider_factory.provider
    assert isinstance(workflow._ai_provider, AIProvider)
    assert recording_provider_factory.provider.requests == []
    assert workflow._repository is workflow._start_processing._repository
    assert workflow._clock is workflow._start_processing._clock
    assert isinstance(workflow._clock, SystemClock)


def test_uploaded_document_processor_is_not_cached() -> None:
    """Composition should return a fresh processor on each call."""
    first_resource_factory = RecordingResourceFactory()
    first_client_factory = RecordingClientFactory()
    second_resource_factory = RecordingResourceFactory()
    second_client_factory = RecordingClientFactory()

    first = build_uploaded_document_processor(
        settings=make_settings(),
        dynamodb_resource_factory=first_resource_factory,
        s3_client_factory=first_client_factory,
    )
    second = build_uploaded_document_processor(
        settings=make_settings(),
        dynamodb_resource_factory=second_resource_factory,
        s3_client_factory=second_client_factory,
    )

    first_workflow = first._workflow
    second_workflow = second._workflow

    assert first is not second
    assert first_workflow is not second_workflow
    assert first_workflow._repository is not second_workflow._repository
    assert first_workflow._clock is not second_workflow._clock
    assert first_workflow._start_processing is not (second_workflow._start_processing)
    assert first_workflow._document_loader is not (second_workflow._document_loader)
    assert first_workflow._ai_provider is not second_workflow._ai_provider
    assert first_workflow._repository._table is not (second_workflow._repository._table)
    assert first_workflow._document_loader._s3_client is not (
        second_workflow._document_loader._s3_client
    )
    assert first_workflow._repository is first_workflow._start_processing._repository
    assert first_workflow._clock is first_workflow._start_processing._clock
    assert second_workflow._repository is (
        second_workflow._start_processing._repository
    )
    assert second_workflow._clock is second_workflow._start_processing._clock
    assert first_workflow._document_loader._s3_client is (first_client_factory.client)
    assert second_workflow._document_loader._s3_client is (second_client_factory.client)
    assert isinstance(first_workflow._ai_provider, MockAIProvider)
    assert isinstance(second_workflow._ai_provider, MockAIProvider)
    assert first_resource_factory.resource is not (second_resource_factory.resource)
    assert first_client_factory.client is not second_client_factory.client


def test_uploaded_document_processor_does_not_require_aws_access() -> None:
    """Processor wiring should succeed without AWS credentials or clients."""
    resource_factory = RecordingResourceFactory()
    client_factory = RecordingClientFactory()

    processor = build_uploaded_document_processor(
        settings=make_settings(),
        dynamodb_resource_factory=resource_factory,
        s3_client_factory=client_factory,
    )

    assert isinstance(processor, ApplicationUploadedDocumentProcessor)
    assert isinstance(processor, UploadedDocumentProcessor)

    workflow = processor._workflow
    start_processing = workflow._start_processing
    document_loader = workflow._document_loader
    ai_provider = workflow._ai_provider

    assert isinstance(start_processing, StartDocumentProcessing)
    assert isinstance(
        workflow._repository,
        DynamoDBDocumentJobRepository,
    )
    assert isinstance(workflow._repository._table, FakeDynamoDBTable)
    assert workflow._repository is start_processing._repository
    assert resource_factory.resource.requested_table_names == [
        "clouddoc-document-jobs",
    ]
    assert workflow._repository._table.name == "clouddoc-document-jobs"
    assert isinstance(workflow._clock, SystemClock)
    assert workflow._clock is start_processing._clock
    assert isinstance(document_loader, S3DocumentTextLoader)
    assert isinstance(document_loader, DocumentTextLoader)
    assert document_loader._s3_client is client_factory.client
    assert isinstance(ai_provider, MockAIProvider)
    assert isinstance(ai_provider, AIProvider)
    assert resource_factory.service_names == [
        "dynamodb",
    ]
    assert client_factory.service_names == [
        "s3",
    ]
