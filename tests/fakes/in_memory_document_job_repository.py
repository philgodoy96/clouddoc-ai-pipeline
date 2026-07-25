"""In-memory document job repository used by automated tests."""

from copy import deepcopy
from datetime import datetime

from clouddoc.domain.document_job import DocumentJob
from clouddoc.domain.job_status import JobStatus
from clouddoc.domain.processing_attempt import ProcessingAttempt
from clouddoc.repositories.document_job_repository import (
    DocumentJobRepository,
)
from clouddoc.repositories.repository_errors import (
    JobAlreadyExistsError,
    JobAttemptMismatchError,
    JobClaimConflictError,
    JobNotFoundError,
    JobStateConflictError,
)
from clouddoc.schemas.ai_output import AIExtractionResult


class InMemoryDocumentJobRepository:
    """Atomic in-memory implementation of the job repository contract."""

    def __init__(self) -> None:
        """Initialize an empty repository."""
        self._jobs: dict[str, DocumentJob] = {}

    def create_job(
        self,
        job: DocumentJob,
    ) -> None:
        """Persist a new document job."""
        if job.job_id in self._jobs:
            raise JobAlreadyExistsError(f"job {job.job_id} already exists")

        self._jobs[job.job_id] = deepcopy(job)

    def get_job(
        self,
        job_id: str,
    ) -> DocumentJob | None:
        """Return an isolated copy of the current job state."""
        job = self._jobs.get(job_id)

        if job is None:
            return None

        return deepcopy(job)

    def claim_job(
        self,
        job_id: str,
        attempt: ProcessingAttempt,
        *,
        claimed_at: datetime,
    ) -> DocumentJob:
        """Acquire processing ownership for a claimable job."""
        current_job = self._get_required_job(job_id)

        if current_job.status is JobStatus.PENDING_UPLOAD:
            updated_job = deepcopy(current_job)
            updated_job.start_processing(
                attempt,
                updated_at=claimed_at,
            )

            return self._replace_and_copy(updated_job)

        if current_job.status is JobStatus.PROCESSING:
            active_attempt = current_job.active_attempt

            if active_attempt is None:
                raise JobStateConflictError("processing job has no active attempt")

            if not active_attempt.is_lease_expired(claimed_at):
                raise JobClaimConflictError(f"job {job_id} already has an active claim")

            reclaimed_job = DocumentJob.rehydrate(
                job_id=current_job.job_id,
                correlation_context=current_job.correlation_context,
                created_at=current_job.created_at,
                updated_at=claimed_at,
                status=JobStatus.PROCESSING,
                attempts=current_job.attempts + 1,
                active_attempt=attempt,
                processing_result=None,
                error_reason=None,
            )

            return self._replace_and_copy(reclaimed_job)

        raise JobStateConflictError(
            f"job {job_id} cannot be claimed from {current_job.status.value}"
        )

    def complete_job(
        self,
        job_id: str,
        attempt_id: str,
        result: AIExtractionResult,
        *,
        completed_at: datetime,
    ) -> DocumentJob:
        """Complete a job successfully for the owning attempt."""
        updated_job = self._copy_for_owned_attempt(
            job_id,
            attempt_id,
        )
        updated_job.mark_succeeded(
            result,
            finished_at=completed_at,
        )

        return self._replace_and_copy(updated_job)

    def fail_job(
        self,
        job_id: str,
        attempt_id: str,
        reason: str,
        *,
        failed_at: datetime,
    ) -> DocumentJob:
        """Complete a job with a terminal failure."""
        updated_job = self._copy_for_owned_attempt(
            job_id,
            attempt_id,
        )
        updated_job.mark_failed(
            reason,
            finished_at=failed_at,
        )

        return self._replace_and_copy(updated_job)

    def release_retryable_claim(
        self,
        job_id: str,
        attempt_id: str,
        *,
        released_at: datetime,
    ) -> DocumentJob:
        """Release processing ownership after a retryable failure."""
        updated_job = self._copy_for_owned_attempt(
            job_id,
            attempt_id,
        )
        updated_job.release_for_retry(
            updated_at=released_at,
        )

        return self._replace_and_copy(updated_job)

    def mark_dead(
        self,
        job_id: str,
        reason: str,
        *,
        marked_at: datetime,
    ) -> DocumentJob:
        """Reconcile retry exhaustion into the dead state."""
        current_job = self._get_required_job(job_id)

        if current_job.status is JobStatus.PROCESSING:
            updated_job = deepcopy(current_job)
            updated_job.mark_dead(
                reason,
                finished_at=marked_at,
            )

            return self._replace_and_copy(updated_job)

        if current_job.status is JobStatus.PENDING_UPLOAD and current_job.attempts >= 1:
            normalized_reason = reason.strip()

            if not normalized_reason:
                raise JobStateConflictError("dead job must have an error reason")

            dead_job = DocumentJob.rehydrate(
                job_id=current_job.job_id,
                correlation_context=current_job.correlation_context,
                created_at=current_job.created_at,
                updated_at=marked_at,
                status=JobStatus.DEAD,
                attempts=current_job.attempts,
                active_attempt=None,
                processing_result=None,
                error_reason=normalized_reason,
            )

            return self._replace_and_copy(dead_job)

        raise JobStateConflictError(
            f"job {job_id} cannot be marked dead from {current_job.status.value}"
        )

    def _get_required_job(
        self,
        job_id: str,
    ) -> DocumentJob:
        """Return the internally stored job or raise when absent."""
        job = self._jobs.get(job_id)

        if job is None:
            raise JobNotFoundError(f"job {job_id} was not found")

        return job

    def _copy_for_owned_attempt(
        self,
        job_id: str,
        attempt_id: str,
    ) -> DocumentJob:
        """Return a copy when the requested attempt owns the claim."""
        current_job = self._get_required_job(job_id)

        if current_job.status is not JobStatus.PROCESSING:
            raise JobStateConflictError(f"job {job_id} is not processing")

        active_attempt = current_job.active_attempt

        if active_attempt is None:
            raise JobStateConflictError("processing job has no active attempt")

        if active_attempt.attempt_id != attempt_id:
            raise JobAttemptMismatchError(
                f"attempt {attempt_id} does not own job {job_id}"
            )

        return deepcopy(current_job)

    def _replace_and_copy(
        self,
        job: DocumentJob,
    ) -> DocumentJob:
        """Atomically replace stored state and return an isolated copy."""
        stored_job = deepcopy(job)
        self._jobs[job.job_id] = stored_job

        return deepcopy(stored_job)


_repository_contract_check: DocumentJobRepository = InMemoryDocumentJobRepository()
