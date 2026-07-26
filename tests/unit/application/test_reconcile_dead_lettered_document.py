"""Tests for dead-lettered document-job reconciliation."""

from datetime import UTC, datetime

import pytest

from clouddoc.application import (
    ApplicationConflictError,
    ApplicationDependencyError,
    ApplicationNotFoundError,
    Clock,
    DeadLetterReason,
    DeadLetterReconciliationOutcome,
    ReconcileDeadLetteredDocument,
)
from clouddoc.domain import (
    CorrelationContext,
    DocumentJob,
    JobStatus,
    ProcessingAttempt,
)
from clouddoc.repositories import (
    JobNotFoundError,
    JobStateConflictError,
    RepositoryError,
)

JOB_ID = "job-001"

CREATED_AT = datetime(
    2026,
    7,
    26,
    12,
    0,
    tzinfo=UTC,
)
ATTEMPT_STARTED_AT = datetime(
    2026,
    7,
    26,
    12,
    1,
    tzinfo=UTC,
)
EXPIRED_LEASE_AT = datetime(
    2026,
    7,
    26,
    12,
    5,
    tzinfo=UTC,
)
ACTIVE_LEASE_AT = datetime(
    2026,
    7,
    26,
    12,
    20,
    tzinfo=UTC,
)
RECONCILED_AT = datetime(
    2026,
    7,
    26,
    12,
    10,
    tzinfo=UTC,
)


class FixedClock:
    """Clock double returning one deterministic timestamp."""

    def __init__(
        self,
        *,
        current_time: datetime = RECONCILED_AT,
    ) -> None:
        """Initialize the clock."""
        self._current_time = current_time
        self.calls = 0

    def now(self) -> datetime:
        """Return the configured timestamp."""
        self.calls += 1
        return self._current_time


class RecordingRepository:
    """Repository double for dead-letter reconciliation."""

    def __init__(
        self,
        *,
        get_results: list[DocumentJob | Exception | None],
        mark_dead_result: DocumentJob,
        mark_dead_error: Exception | None = None,
    ) -> None:
        """Initialize deterministic repository behavior."""
        self._get_results = list(get_results)
        self._mark_dead_result = mark_dead_result
        self._mark_dead_error = mark_dead_error

        self.get_calls: list[str] = []
        self.mark_dead_calls: list[dict[str, object]] = []

    def get_job(
        self,
        job_id: str,
    ) -> DocumentJob | None:
        """Return or raise the next configured lookup result."""
        self.get_calls.append(job_id)

        if not self._get_results:
            raise AssertionError("unexpected additional get_job call")

        result = self._get_results.pop(0)

        if isinstance(result, Exception):
            raise result

        return result

    def mark_dead(
        self,
        job_id: str,
        reason: str,
        *,
        expected_updated_at: datetime,
        marked_at: datetime,
    ) -> DocumentJob:
        """Record one dead-state transition attempt."""
        self.mark_dead_calls.append(
            {
                "job_id": job_id,
                "reason": reason,
                "expected_updated_at": expected_updated_at,
                "marked_at": marked_at,
            }
        )

        if self._mark_dead_error is not None:
            raise self._mark_dead_error

        return self._mark_dead_result


def make_correlation_context() -> CorrelationContext:
    """Create deterministic workflow identifiers."""
    return CorrelationContext(
        request_id="request-001",
        correlation_id="correlation-001",
    )


def make_attempt(
    *,
    lease_expires_at: datetime,
) -> ProcessingAttempt:
    """Create one deterministic processing attempt."""
    return ProcessingAttempt(
        attempt_id="attempt-001",
        started_at=ATTEMPT_STARTED_AT,
        lease_expires_at=lease_expires_at,
    )


def make_job(
    *,
    status: JobStatus,
    attempts: int = 1,
    lease_expires_at: datetime = EXPIRED_LEASE_AT,
) -> DocumentJob:
    """Create one valid job in the requested lifecycle state."""
    if status is JobStatus.PENDING_UPLOAD and attempts == 0:
        return DocumentJob(
            job_id=JOB_ID,
            correlation_context=make_correlation_context(),
            created_at=CREATED_AT,
            updated_at=CREATED_AT,
        )

    active_attempt = None
    processing_result = None
    error_reason = None

    if status is JobStatus.PROCESSING:
        active_attempt = make_attempt(
            lease_expires_at=lease_expires_at,
        )
    elif status is JobStatus.SUCCEEDED:
        processing_result = {
            "document_type": "contract",
        }
    elif status is JobStatus.FAILED:
        error_reason = "document_validation_failed"
    elif status is JobStatus.DEAD:
        error_reason = "processing_retries_exhausted"

    return DocumentJob.rehydrate(
        job_id=JOB_ID,
        correlation_context=make_correlation_context(),
        created_at=CREATED_AT,
        updated_at=ATTEMPT_STARTED_AT,
        status=status,
        attempts=attempts,
        active_attempt=active_attempt,
        processing_result=processing_result,
        error_reason=error_reason,
    )


def make_dead_job() -> DocumentJob:
    """Create one durably reconciled dead job."""
    return DocumentJob.rehydrate(
        job_id=JOB_ID,
        correlation_context=make_correlation_context(),
        created_at=CREATED_AT,
        updated_at=RECONCILED_AT,
        status=JobStatus.DEAD,
        attempts=1,
        active_attempt=None,
        processing_result=None,
        error_reason=(DeadLetterReason.PROCESSING_RETRIES_EXHAUSTED.value),
    )


def make_service(
    *,
    get_results: list[DocumentJob | Exception | None],
    mark_dead_error: Exception | None = None,
) -> tuple[
    ReconcileDeadLetteredDocument,
    RecordingRepository,
    FixedClock,
]:
    """Create the service and deterministic collaborators."""
    repository = RecordingRepository(
        get_results=get_results,
        mark_dead_result=make_dead_job(),
        mark_dead_error=mark_dead_error,
    )
    clock = FixedClock()
    service = ReconcileDeadLetteredDocument(
        repository=repository,
        clock=clock,
    )

    return service, repository, clock


def test_clock_double_satisfies_application_port() -> None:
    """The fixed clock should satisfy the structural clock contract."""
    assert isinstance(
        FixedClock(),
        Clock,
    )


def test_marks_expired_processing_job_dead() -> None:
    """An expired processing attempt should be reconciled."""
    observed_job = make_job(
        status=JobStatus.PROCESSING,
        lease_expires_at=EXPIRED_LEASE_AT,
    )
    service, repository, clock = make_service(
        get_results=[
            observed_job,
        ],
    )

    result = service.execute(
        job_id=JOB_ID,
    )

    assert result.outcome is DeadLetterReconciliationOutcome.DEAD_RECORDED
    assert result.job_id == JOB_ID

    assert repository.get_calls == [
        JOB_ID,
    ]
    assert repository.mark_dead_calls == [
        {
            "job_id": JOB_ID,
            "reason": (DeadLetterReason.PROCESSING_RETRIES_EXHAUSTED.value),
            "expected_updated_at": observed_job.updated_at,
            "marked_at": RECONCILED_AT,
        }
    ]
    assert clock.calls == 1


def test_marks_released_attempted_job_dead() -> None:
    """A retry-ready attempted job should be reconciled."""
    observed_job = make_job(
        status=JobStatus.PENDING_UPLOAD,
        attempts=1,
    )
    service, repository, clock = make_service(
        get_results=[
            observed_job,
        ],
    )

    result = service.execute(
        job_id=JOB_ID,
    )

    assert result.outcome is DeadLetterReconciliationOutcome.DEAD_RECORDED
    assert repository.mark_dead_calls == [
        {
            "job_id": JOB_ID,
            "reason": (DeadLetterReason.PROCESSING_RETRIES_EXHAUSTED.value),
            "expected_updated_at": observed_job.updated_at,
            "marked_at": RECONCILED_AT,
        }
    ]
    assert clock.calls == 1


@pytest.mark.parametrize(
    "status",
    [
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.DEAD,
    ],
)
def test_acknowledges_terminal_job_without_mutation(
    status: JobStatus,
) -> None:
    """An authoritative terminal state should win reconciliation."""
    service, repository, clock = make_service(
        get_results=[
            make_job(
                status=status,
            )
        ],
    )

    result = service.execute(
        job_id=JOB_ID,
    )

    assert result.outcome is (DeadLetterReconciliationOutcome.EFFECT_ALREADY_APPLIED)
    assert result.job_id == JOB_ID
    assert repository.mark_dead_calls == []
    assert clock.calls == 0


def test_preserves_unexpired_processing_attempt() -> None:
    """A healthy active worker must not be marked dead."""
    service, repository, clock = make_service(
        get_results=[
            make_job(
                status=JobStatus.PROCESSING,
                lease_expires_at=ACTIVE_LEASE_AT,
            )
        ],
    )

    with pytest.raises(
        ApplicationConflictError,
        match=("document job has an active processing attempt"),
    ):
        service.execute(
            job_id=JOB_ID,
        )

    assert repository.mark_dead_calls == []
    assert clock.calls == 1


def test_rejects_pending_job_without_processing_attempt() -> None:
    """An untouched upload job does not prove retry exhaustion."""
    service, repository, clock = make_service(
        get_results=[
            make_job(
                status=JobStatus.PENDING_UPLOAD,
                attempts=0,
            )
        ],
    )

    with pytest.raises(
        ApplicationConflictError,
        match=("document job has no exhausted processing attempt"),
    ):
        service.execute(
            job_id=JOB_ID,
        )

    assert repository.mark_dead_calls == []
    assert clock.calls == 0


def test_missing_job_remains_retryable() -> None:
    """A missing business resource must not be acknowledged."""
    service, repository, clock = make_service(
        get_results=[
            None,
        ],
    )

    with pytest.raises(
        ApplicationNotFoundError,
        match=f"document job {JOB_ID} was not found",
    ):
        service.execute(
            job_id=JOB_ID,
        )

    assert repository.mark_dead_calls == []
    assert clock.calls == 0


def test_normalizes_lookup_dependency_failure() -> None:
    """Repository lookup failures should remain retryable."""
    repository_error = RepositoryError("DynamoDB unavailable")
    service, repository, clock = make_service(
        get_results=[
            repository_error,
        ],
    )

    with pytest.raises(
        ApplicationDependencyError,
        match=("failed to load dead-lettered document job"),
    ) as captured_error:
        service.execute(
            job_id=JOB_ID,
        )

    assert captured_error.value.cause is repository_error
    assert captured_error.value.__cause__ is repository_error
    assert captured_error.value.context == {
        "job_id": JOB_ID,
    }
    assert repository.mark_dead_calls == []
    assert clock.calls == 0


def test_normalizes_job_disappearing_during_mark_dead() -> None:
    """A removed job must not produce false reconciliation success."""
    observed_job = make_job(
        status=JobStatus.PENDING_UPLOAD,
        attempts=1,
    )
    repository_error = JobNotFoundError("job disappeared")
    service, repository, clock = make_service(
        get_results=[
            observed_job,
        ],
        mark_dead_error=repository_error,
    )

    with pytest.raises(
        ApplicationNotFoundError,
        match=f"document job {JOB_ID} was not found",
    ) as captured_error:
        service.execute(
            job_id=JOB_ID,
        )

    assert captured_error.value.__cause__ is repository_error
    assert repository.mark_dead_calls == [
        {
            "job_id": JOB_ID,
            "reason": (DeadLetterReason.PROCESSING_RETRIES_EXHAUSTED.value),
            "expected_updated_at": observed_job.updated_at,
            "marked_at": RECONCILED_AT,
        }
    ]
    assert clock.calls == 1


def test_normalizes_mark_dead_dependency_failure() -> None:
    """A failed persistence operation must remain retryable."""
    observed_job = make_job(
        status=JobStatus.PENDING_UPLOAD,
        attempts=1,
    )
    repository_error = RepositoryError("DynamoDB unavailable")
    service, repository, clock = make_service(
        get_results=[
            observed_job,
        ],
        mark_dead_error=repository_error,
    )

    with pytest.raises(
        ApplicationDependencyError,
        match=("failed to mark dead-lettered document job dead"),
    ) as captured_error:
        service.execute(
            job_id=JOB_ID,
        )

    assert captured_error.value.cause is repository_error
    assert captured_error.value.__cause__ is repository_error
    assert captured_error.value.context == {
        "job_id": JOB_ID,
        "operation": "mark_dead",
    }
    assert repository.mark_dead_calls == [
        {
            "job_id": JOB_ID,
            "reason": (DeadLetterReason.PROCESSING_RETRIES_EXHAUSTED.value),
            "expected_updated_at": observed_job.updated_at,
            "marked_at": RECONCILED_AT,
        }
    ]
    assert clock.calls == 1


@pytest.mark.parametrize(
    "terminal_status",
    [
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.DEAD,
    ],
)
def test_reconciles_conditional_race_to_terminal_state(
    terminal_status: JobStatus,
) -> None:
    """A concurrently recorded terminal state should win."""
    observed_job = make_job(
        status=JobStatus.PENDING_UPLOAD,
        attempts=1,
    )
    conflict = JobStateConflictError("conditional update failed")
    service, repository, clock = make_service(
        get_results=[
            observed_job,
            make_job(
                status=terminal_status,
            ),
        ],
        mark_dead_error=conflict,
    )

    result = service.execute(
        job_id=JOB_ID,
    )

    assert result.outcome is (DeadLetterReconciliationOutcome.EFFECT_ALREADY_APPLIED)
    assert repository.get_calls == [
        JOB_ID,
        JOB_ID,
    ]
    assert repository.mark_dead_calls == [
        {
            "job_id": JOB_ID,
            "reason": (DeadLetterReason.PROCESSING_RETRIES_EXHAUSTED.value),
            "expected_updated_at": observed_job.updated_at,
            "marked_at": RECONCILED_AT,
        }
    ]
    assert clock.calls == 1


def test_rejects_conditional_race_to_nonterminal_state() -> None:
    """A new processing owner must survive stale reconciliation."""
    observed_job = make_job(
        status=JobStatus.PENDING_UPLOAD,
        attempts=1,
    )
    conflict = JobStateConflictError("conditional update failed")
    service, repository, clock = make_service(
        get_results=[
            observed_job,
            make_job(
                status=JobStatus.PROCESSING,
                lease_expires_at=ACTIVE_LEASE_AT,
            ),
        ],
        mark_dead_error=conflict,
    )

    with pytest.raises(
        ApplicationConflictError,
        match=("document job changed before dead-letter reconciliation completed"),
    ) as captured_error:
        service.execute(
            job_id=JOB_ID,
        )

    assert captured_error.value.__cause__ is conflict
    assert repository.get_calls == [
        JOB_ID,
        JOB_ID,
    ]
    assert repository.mark_dead_calls == [
        {
            "job_id": JOB_ID,
            "reason": (DeadLetterReason.PROCESSING_RETRIES_EXHAUSTED.value),
            "expected_updated_at": observed_job.updated_at,
            "marked_at": RECONCILED_AT,
        }
    ]
    assert clock.calls == 1


def test_unexpected_mark_dead_failure_propagates() -> None:
    """Unexpected repository defects should reach the outer boundary."""
    observed_job = make_job(
        status=JobStatus.PENDING_UPLOAD,
        attempts=1,
    )
    unexpected_error = RuntimeError("unexpected repository defect")
    service, repository, clock = make_service(
        get_results=[
            observed_job,
        ],
        mark_dead_error=unexpected_error,
    )

    with pytest.raises(
        RuntimeError,
        match="unexpected repository defect",
    ):
        service.execute(
            job_id=JOB_ID,
        )

    assert repository.mark_dead_calls == [
        {
            "job_id": JOB_ID,
            "reason": (DeadLetterReason.PROCESSING_RETRIES_EXHAUSTED.value),
            "expected_updated_at": observed_job.updated_at,
            "marked_at": RECONCILED_AT,
        }
    ]
    assert clock.calls == 1
