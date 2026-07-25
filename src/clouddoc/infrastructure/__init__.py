"""Concrete infrastructure adapters used at runtime."""

from clouddoc.infrastructure.clock import SystemClock
from clouddoc.infrastructure.identifiers import UUIDJobIdGenerator
from clouddoc.infrastructure.no_op_processing import NoOpUploadedDocumentProcessor
from clouddoc.infrastructure.s3_uploads import S3PresignedDocumentUploadProvider

__all__ = [
    "NoOpUploadedDocumentProcessor",
    "S3PresignedDocumentUploadProvider",
    "SystemClock",
    "UUIDJobIdGenerator",
]
