"""Concrete infrastructure adapters used at runtime."""

from clouddoc.infrastructure.application_processing import (
    ApplicationUploadedDocumentProcessor,
)
from clouddoc.infrastructure.clock import SystemClock
from clouddoc.infrastructure.identifiers import (
    UUIDJobIdGenerator,
    UUIDProcessingAttemptIdGenerator,
)
from clouddoc.infrastructure.no_op_processing import NoOpUploadedDocumentProcessor
from clouddoc.infrastructure.s3_documents import S3DocumentTextLoader
from clouddoc.infrastructure.s3_uploads import S3PresignedDocumentUploadProvider

__all__ = [
    "ApplicationUploadedDocumentProcessor",
    "NoOpUploadedDocumentProcessor",
    "S3DocumentTextLoader",
    "S3PresignedDocumentUploadProvider",
    "SystemClock",
    "UUIDJobIdGenerator",
    "UUIDProcessingAttemptIdGenerator",
]
