"""Application-facing document job repository contract."""

from datetime import datetime
from typing import Protocol, runtime_checkable

from clouddoc.domain.document_job import DocumentJob
from clouddoc.domain.processing_attempt import ProcessingAttempt
from clouddoc.schemas.ai_output import AIExtractionResult


@runtime_checkable
class DocumentJobRepository(Protocol):
    """Persistence contract for document job lifecycle operations."""

    def create_job(
        self,
        job: DocumentJob,
    ) -> None:
        """Persist a new document job."""

    def get_job(
        self,
        job_id: str,
    ) -> DocumentJob | None:
        """Return the current job state when it exists."""

    def claim_job(
        self,
        job_id: str,
        attempt: ProcessingAttempt,
        *,
        claimed_at: datetime,
    ) -> DocumentJob:
        """Acquire processing ownership for a claimable job."""

    def complete_job(
        self,
        job_id: str,
        attempt_id: str,
        result: AIExtractionResult,
        *,
        completed_at: datetime,
    ) -> DocumentJob:
        """Complete a job successfully for the owning attempt."""

    def fail_job(
        self,
        job_id: str,
        attempt_id: str,
        reason: str,
        *,
        failed_at: datetime,
    ) -> DocumentJob:
        """Complete a job with a terminal failure."""

    def release_retryable_claim(
        self,
        job_id: str,
        attempt_id: str,
        *,
        released_at: datetime,
    ) -> DocumentJob:
        """Release processing ownership after a retryable failure."""

    def mark_dead(
        self,
        job_id: str,
        reason: str,
        *,
        expected_updated_at: datetime,
        marked_at: datetime,
    ) -> DocumentJob:
        """Reconcile retry exhaustion from one observed job snapshot."""
