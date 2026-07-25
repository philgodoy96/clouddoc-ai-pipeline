"""Document job persistence contracts and implementations."""

from clouddoc.repositories.document_job_repository import (
    DocumentJobRepository,
)
from clouddoc.repositories.dynamodb_document_job_repository import (
    DynamoDBDocumentJobRepository,
)
from clouddoc.repositories.repository_errors import (
    JobAlreadyExistsError,
    JobAttemptMismatchError,
    JobClaimConflictError,
    JobNotFoundError,
    JobStateConflictError,
    RepositoryError,
)

__all__ = [
    "DocumentJobRepository",
    "DynamoDBDocumentJobRepository",
    "JobAlreadyExistsError",
    "JobAttemptMismatchError",
    "JobClaimConflictError",
    "JobNotFoundError",
    "JobStateConflictError",
    "RepositoryError",
]
