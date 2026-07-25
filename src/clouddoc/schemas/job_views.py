"""Application-facing document job views."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from clouddoc.domain import DocumentJob, JobStatus


class DocumentJobView(BaseModel):
    """Stable application representation of a document job."""

    model_config = ConfigDict(frozen=True)

    job_id: str
    status: JobStatus
    request_id: str
    correlation_id: str
    created_at: datetime
    updated_at: datetime
    attempts: int
    error_reason: str | None

    @classmethod
    def from_job(
        cls,
        job: DocumentJob,
    ) -> "DocumentJobView":
        """Create a detached application view from a domain job."""
        return cls(
            job_id=job.job_id,
            status=job.status,
            request_id=job.correlation_context.request_id,
            correlation_id=job.correlation_context.correlation_id,
            created_at=job.created_at,
            updated_at=job.updated_at,
            attempts=job.attempts,
            error_reason=job.error_reason,
        )
