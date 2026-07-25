"""Runtime configuration and dependency composition."""

from clouddoc.runtime.composition import (
    build_create_document_job_service,
    build_document_job_repository,
    build_document_upload_provider,
    build_get_document_job_service,
)
from clouddoc.runtime.settings import (
    DEFAULT_UPLOAD_URL_EXPIRATION_SECONDS,
    DOCUMENTS_BUCKET_NAME_ENV_VAR,
    JOBS_TABLE_NAME_ENV_VAR,
    UPLOAD_URL_EXPIRATION_SECONDS_ENV_VAR,
    RuntimeConfigurationError,
    RuntimeSettings,
)

__all__ = [
    "DEFAULT_UPLOAD_URL_EXPIRATION_SECONDS",
    "DOCUMENTS_BUCKET_NAME_ENV_VAR",
    "JOBS_TABLE_NAME_ENV_VAR",
    "UPLOAD_URL_EXPIRATION_SECONDS_ENV_VAR",
    "RuntimeConfigurationError",
    "RuntimeSettings",
    "build_create_document_job_service",
    "build_document_job_repository",
    "build_document_upload_provider",
    "build_get_document_job_service",
]
