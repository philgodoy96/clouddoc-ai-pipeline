"""Normalized terminal failure reasons for document processing."""

from enum import StrEnum


class ProcessingFailureReason(StrEnum):
    """Describe one safe, stable terminal processing failure."""

    DOCUMENT_NOT_FOUND = "document_not_found"
    DOCUMENT_VALIDATION_FAILED = "document_validation_failed"
    INVALID_DOCUMENT_REFERENCE = "invalid_document_reference"
    INVALID_PROVIDER_REQUEST = "invalid_provider_request"
    AI_PROVIDER_INVALID_RESPONSE = "ai_provider_invalid_response"
