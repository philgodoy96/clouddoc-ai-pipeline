"""Application service for reconciling dead-lettered document jobs."""

from datetime import datetime

from clouddoc.application.dead_letter_reasons import (
    DeadLetterReason,
)
from clouddoc.application.dead_letter_results import (
    DeadLetterReconciliationResult,
)
from clouddoc.application.errors import (
    ApplicationConflictError,
    ApplicationDependencyError,
    ApplicationNotFoundError,
)
from clouddoc.application.ports import Clock
from clouddoc.domain import DocumentJob, JobStatus
from clouddoc.repositories import (
    DocumentJobRepository,
    JobNotFoundError,
    JobStateConflictError,
    RepositoryError,
)


class ReconcileDeadLetteredDocument:
    """Reconcile exhausted queue delivery with authoritative job state."""

    def __init__(
        self,
        *,
        repository: DocumentJobRepository,
        clock: Clock,
    ) -> None:
        """Initialize the service with explicit dependencies."""
        self._repository = repository
        self._clock = clock

    def execute(
        self,
        *,
        job_id: str,
    ) -> DeadLetterReconciliationResult:
        """Record retry exhaustion when the job remains unfinished."""
        job = self._get_job(job_id)

        if job.status.is_terminal:
            return DeadLetterReconciliationResult.effect_already_applied(
                job_id=job.job_id,
            )

        marked_at = self._require_reconciliation_eligibility(
            job=job,
        )

        try:
            self._repository.mark_dead(
                job.job_id,
                DeadLetterReason.PROCESSING_RETRIES_EXHAUSTED.value,
                marked_at=marked_at,
            )
        except JobNotFoundError as error:
            raise ApplicationNotFoundError(
                f"document job {job.job_id} was not found"
            ) from error
        except JobStateConflictError as error:
            return self._reconcile_state_conflict(
                job_id=job.job_id,
                cause=error,
            )
        except RepositoryError as error:
            raise ApplicationDependencyError(
                "failed to mark dead-lettered document job dead",
                cause=error,
                context={
                    "job_id": job.job_id,
                    "operation": "mark_dead",
                },
            ) from error

        return DeadLetterReconciliationResult.dead_recorded(
            job_id=job.job_id,
        )

    def _get_job(
        self,
        job_id: str,
    ) -> DocumentJob:
        """Load one authoritative document job."""
        try:
            job = self._repository.get_job(job_id)
        except RepositoryError as error:
            raise ApplicationDependencyError(
                "failed to load dead-lettered document job",
                cause=error,
                context={
                    "job_id": job_id,
                },
            ) from error

        if job is None:
            raise ApplicationNotFoundError(f"document job {job_id} was not found")

        return job

    def _require_reconciliation_eligibility(
        self,
        *,
        job: DocumentJob,
    ) -> datetime:
        """Return the reconciliation timestamp for an eligible job."""
        if job.status is JobStatus.PENDING_UPLOAD:
            if job.attempts < 1:
                raise ApplicationConflictError(
                    "document job has no exhausted processing attempt"
                )

            return self._clock.now()

        if job.status is JobStatus.PROCESSING:
            active_attempt = job.active_attempt

            if active_attempt is None:
                raise ApplicationConflictError("processing job has no active attempt")

            observed_at = self._clock.now()

            if not active_attempt.is_lease_expired(observed_at):
                raise ApplicationConflictError(
                    "document job has an active processing attempt"
                )

            return observed_at

        raise ApplicationConflictError(
            "document job is not eligible for dead-letter reconciliation"
        )

    def _reconcile_state_conflict(
        self,
        *,
        job_id: str,
        cause: Exception,
    ) -> DeadLetterReconciliationResult:
        """Resolve a failed conditional dead transition."""
        current_job = self._get_job(job_id)

        if current_job.status.is_terminal:
            return DeadLetterReconciliationResult.effect_already_applied(
                job_id=current_job.job_id,
            )

        raise ApplicationConflictError(
            "document job changed before dead-letter reconciliation completed"
        ) from cause
