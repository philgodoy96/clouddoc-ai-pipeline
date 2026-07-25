"""Application service for retrieving document jobs."""

from dataclasses import dataclass

from clouddoc.application.errors import (
    ApplicationDependencyError,
    ApplicationNotFoundError,
)
from clouddoc.repositories import (
    DocumentJobRepository,
    RepositoryError,
)
from clouddoc.schemas.job_views import DocumentJobView


@dataclass(frozen=True, slots=True)
class GetDocumentJobQuery:
    """Input required to retrieve one document job."""

    job_id: str


class GetDocumentJob:
    """Retrieve a document job through the repository boundary."""

    def __init__(
        self,
        *,
        repository: DocumentJobRepository,
    ) -> None:
        """Initialize the service with its repository dependency."""
        self._repository = repository

    def execute(
        self,
        query: GetDocumentJobQuery,
    ) -> DocumentJobView:
        """Retrieve one job and return a detached application view."""
        try:
            job = self._repository.get_job(query.job_id)
        except RepositoryError as error:
            raise ApplicationDependencyError(
                "failed to retrieve document job",
                cause=error,
                context={
                    "job_id": query.job_id,
                },
            ) from error

        if job is None:
            raise ApplicationNotFoundError(f"document job {query.job_id} was not found")

        return DocumentJobView.from_job(job)
