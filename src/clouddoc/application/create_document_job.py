"""Application service for creating document jobs."""

from dataclasses import dataclass

from clouddoc.application.errors import (
    ApplicationConflictError,
    ApplicationDependencyError,
)
from clouddoc.application.ports import Clock, JobIdGenerator
from clouddoc.domain import CorrelationContext, DocumentJob
from clouddoc.repositories import (
    DocumentJobRepository,
    JobAlreadyExistsError,
    RepositoryError,
)
from clouddoc.schemas.job_views import DocumentJobView


@dataclass(frozen=True, slots=True)
class CreateDocumentJobCommand:
    """Input required to create a document-processing job."""

    request_id: str
    correlation_id: str


class CreateDocumentJob:
    """Create and persist a new pending document job."""

    def __init__(
        self,
        *,
        repository: DocumentJobRepository,
        clock: Clock,
        job_id_generator: JobIdGenerator,
    ) -> None:
        """Initialize the service with application-layer dependencies."""
        self._repository = repository
        self._clock = clock
        self._job_id_generator = job_id_generator

    def execute(
        self,
        command: CreateDocumentJobCommand,
    ) -> DocumentJobView:
        """Create a document job and return a detached application view."""
        job_id = self._job_id_generator.generate()
        current_time = self._clock.now()

        job = DocumentJob(
            job_id=job_id,
            correlation_context=CorrelationContext(
                request_id=command.request_id,
                correlation_id=command.correlation_id,
            ),
            created_at=current_time,
            updated_at=current_time,
        )

        try:
            self._repository.create_job(job)
        except JobAlreadyExistsError as error:
            raise ApplicationConflictError(
                f"document job {job_id} already exists"
            ) from error
        except RepositoryError as error:
            raise ApplicationDependencyError(
                "failed to persist document job",
                cause=error,
                context={
                    "job_id": job_id,
                },
            ) from error

        return DocumentJobView.from_job(job)
