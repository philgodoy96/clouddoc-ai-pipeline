"""Tests for runtime dependency composition."""

from typing import Any

from clouddoc.application import (
    CreateDocumentJob,
    GetDocumentJob,
)
from clouddoc.infrastructure import (
    SystemClock,
    UUIDJobIdGenerator,
)
from clouddoc.repositories import (
    DynamoDBDocumentJobRepository,
)
from clouddoc.runtime.composition import (
    build_create_document_job_service,
    build_document_job_repository,
    build_get_document_job_service,
)
from clouddoc.runtime.settings import RuntimeSettings


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


def make_settings() -> RuntimeSettings:
    """Create valid runtime settings."""
    return RuntimeSettings(
        jobs_table_name="clouddoc-document-jobs",
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

    service = build_create_document_job_service(
        settings=make_settings(),
        dynamodb_resource_factory=resource_factory,
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


def test_composition_does_not_require_real_aws_access() -> None:
    """Dependency wiring should be testable without network access."""
    resource_factory = RecordingResourceFactory()

    services: tuple[Any, ...] = (
        build_create_document_job_service(
            settings=make_settings(),
            dynamodb_resource_factory=resource_factory,
        ),
        build_get_document_job_service(
            settings=make_settings(),
            dynamodb_resource_factory=resource_factory,
        ),
    )

    assert all(services)
    assert resource_factory.service_names == [
        "dynamodb",
        "dynamodb",
    ]
