"""Application service for acquiring document-processing ownership."""

from datetime import timedelta

from clouddoc.application.errors import (
    ApplicationConflictError,
    ApplicationDependencyError,
    ApplicationNotFoundError,
)
from clouddoc.application.ports import (
    Clock,
    ProcessingAttemptIdGenerator,
)
from clouddoc.application.processing_results import (
    ProcessingStartResult,
)
from clouddoc.delivery.events.models import UploadedDocumentEvent
from clouddoc.domain import (
    JobStatus,
    ProcessingAttempt,
)
from clouddoc.repositories import (
    DocumentJobRepository,
    JobClaimConflictError,
    JobNotFoundError,
    JobStateConflictError,
    RepositoryError,
)
from clouddoc.schemas.document_keys import (
    build_document_object_key,
)


class StartDocumentProcessing:
    """Acquire an idempotent processing claim for an uploaded document."""

    def __init__(
        self,
        *,
        repository: DocumentJobRepository,
        clock: Clock,
        attempt_id_generator: ProcessingAttemptIdGenerator,
        lease_duration: timedelta,
    ) -> None:
        """Initialize the service with explicit processing dependencies."""
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")

        self._repository = repository
        self._clock = clock
        self._attempt_id_generator = attempt_id_generator
        self._lease_duration = lease_duration

    def execute(
        self,
        *,
        event: UploadedDocumentEvent,
    ) -> ProcessingStartResult:
        """Acquire processing ownership or accept an applied duplicate."""
        claimed_at = self._clock.now()
        job = self._get_job(event.job_id)

        self._validate_object_ownership(
            event=event,
            authoritative_job_id=job.job_id,
        )

        if job.status is JobStatus.SUCCEEDED:
            return ProcessingStartResult.effect_already_applied()

        if job.status is JobStatus.PROCESSING:
            active_attempt = job.active_attempt

            if active_attempt is None:
                raise ApplicationConflictError(
                    f"processing job {job.job_id} has no active attempt"
                )

            if not active_attempt.is_lease_expired(claimed_at):
                return ProcessingStartResult.effect_already_applied()

        elif job.status is not JobStatus.PENDING_UPLOAD:
            raise ApplicationConflictError(
                f"job {job.job_id} cannot start processing from {job.status.value}"
            )

        attempt = ProcessingAttempt(
            attempt_id=self._attempt_id_generator.generate(),
            started_at=claimed_at,
            lease_expires_at=claimed_at + self._lease_duration,
        )

        try:
            self._repository.claim_job(
                job.job_id,
                attempt,
                claimed_at=claimed_at,
            )
        except JobNotFoundError as error:
            raise ApplicationNotFoundError(
                f"document job {job.job_id} was not found"
            ) from error
        except (
            JobClaimConflictError,
            JobStateConflictError,
        ) as error:
            return self._reconcile_claim_conflict(
                job_id=job.job_id,
                observed_at=claimed_at,
                cause=error,
            )
        except RepositoryError as error:
            raise ApplicationDependencyError(
                "failed to claim document job",
                cause=error,
                context={
                    "job_id": job.job_id,
                    "attempt_id": attempt.attempt_id,
                },
            ) from error

        return ProcessingStartResult.claim_acquired(
            attempt=attempt,
        )

    def _get_job(
        self,
        job_id: str,
    ):
        """Load the authoritative job through the repository boundary."""
        try:
            job = self._repository.get_job(job_id)
        except RepositoryError as error:
            raise ApplicationDependencyError(
                "failed to load document job",
                cause=error,
                context={
                    "job_id": job_id,
                },
            ) from error

        if job is None:
            raise ApplicationNotFoundError(f"document job {job_id} was not found")

        return job

    def _reconcile_claim_conflict(
        self,
        *,
        job_id: str,
        observed_at,
        cause: Exception,
    ) -> ProcessingStartResult:
        """Resolve a conditional claim race against authoritative state."""
        current_job = self._get_job(job_id)

        if current_job.status is JobStatus.SUCCEEDED:
            return ProcessingStartResult.effect_already_applied()

        if current_job.status is JobStatus.PROCESSING:
            active_attempt = current_job.active_attempt

            if active_attempt is not None and not active_attempt.is_lease_expired(
                observed_at
            ):
                return ProcessingStartResult.effect_already_applied()

        raise ApplicationConflictError(
            f"document job {job_id} could not acquire processing ownership"
        ) from cause

    @staticmethod
    def _validate_object_ownership(
        *,
        event: UploadedDocumentEvent,
        authoritative_job_id: str,
    ) -> None:
        """Ensure the uploaded object belongs to the authoritative job."""
        expected_object_key = build_document_object_key(authoritative_job_id)

        if event.object_key != expected_object_key:
            raise ApplicationConflictError(
                f"uploaded object does not belong to "
                f"document job {authoritative_job_id}"
            )
