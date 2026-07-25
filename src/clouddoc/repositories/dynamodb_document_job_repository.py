"""DynamoDB implementation of the document job repository contract."""

from copy import deepcopy
from datetime import datetime
from typing import Any

from botocore.exceptions import ClientError

from clouddoc.domain import (
    DocumentJob,
    JobStatus,
    ProcessingAttempt,
)
from clouddoc.repositories.document_job_repository import (
    DocumentJobRepository,
)
from clouddoc.repositories.repository_errors import (
    JobAlreadyExistsError,
    JobAttemptMismatchError,
    JobClaimConflictError,
    JobNotFoundError,
    JobStateConflictError,
    RepositoryError,
)
from clouddoc.schemas.ai_output import AIExtractionResult
from clouddoc.schemas.persistence_models import (
    build_job_partition_key,
    document_job_from_item,
    document_job_to_item,
)

_CONDITIONAL_CHECK_FAILED = "ConditionalCheckFailedException"


class DynamoDBDocumentJobRepository:
    """DynamoDB-backed document job repository."""

    def __init__(
        self,
        *,
        table: Any,
    ) -> None:
        """Initialize the repository with a DynamoDB Table resource."""
        self._table = table

    def create_job(
        self,
        job: DocumentJob,
    ) -> None:
        """Persist a new document job conditionally."""
        try:
            self._table.put_item(
                Item=document_job_to_item(job),
                ConditionExpression="attribute_not_exists(#pk)",
                ExpressionAttributeNames={
                    "#pk": "pk",
                },
            )
        except ClientError as error:
            if _is_conditional_check_failure(error):
                raise JobAlreadyExistsError(
                    f"job {job.job_id} already exists"
                ) from error

            raise _repository_error(
                "failed to create document job",
                error,
            ) from error

    def get_job(
        self,
        job_id: str,
    ) -> DocumentJob | None:
        """Return the current persisted job state."""
        try:
            response = self._table.get_item(
                Key={
                    "pk": build_job_partition_key(job_id),
                },
                ConsistentRead=True,
            )
        except ClientError as error:
            raise _repository_error(
                "failed to get document job",
                error,
            ) from error

        item = response.get("Item")

        if item is None:
            return None

        return document_job_from_item(item)

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

            condition_expression = (
                "#status = :pending AND #updated_at = :expected_updated_at"
            )
            expression_names = {
                "#status": "status",
                "#updated_at": "updated_at",
            }
            expression_values = {
                ":pending": JobStatus.PENDING_UPLOAD.value,
                ":expected_updated_at": (current_job.updated_at.isoformat()),
            }

        elif current_job.status is JobStatus.PROCESSING:
            active_attempt = current_job.active_attempt

            if active_attempt is None:
                raise JobStateConflictError("processing job has no active attempt")

            if not active_attempt.is_lease_expired(claimed_at):
                raise JobClaimConflictError(f"job {job_id} already has an active claim")

            updated_job = DocumentJob.rehydrate(
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

            condition_expression = (
                "#status = :processing "
                "AND #lease_expires_at <= :claimed_at "
                "AND #updated_at = :expected_updated_at"
            )
            expression_names = {
                "#status": "status",
                "#lease_expires_at": "active_attempt_lease_expires_at",
                "#updated_at": "updated_at",
            }
            expression_values = {
                ":processing": JobStatus.PROCESSING.value,
                ":claimed_at": claimed_at.isoformat(),
                ":expected_updated_at": (current_job.updated_at.isoformat()),
            }

        else:
            raise JobStateConflictError(
                f"job {job_id} cannot be claimed from {current_job.status.value}"
            )

        try:
            self._table.put_item(
                Item=document_job_to_item(updated_job),
                ConditionExpression=condition_expression,
                ExpressionAttributeNames=expression_names,
                ExpressionAttributeValues=expression_values,
            )
        except ClientError as error:
            if _is_conditional_check_failure(error):
                self._raise_claim_conflict(
                    job_id,
                    claimed_at=claimed_at,
                )

            raise _repository_error(
                "failed to claim document job",
                error,
            ) from error

        return deepcopy(updated_job)

    def complete_job(
        self,
        job_id: str,
        attempt_id: str,
        result: AIExtractionResult,
        *,
        completed_at: datetime,
    ) -> DocumentJob:
        """Complete a job successfully for the owning attempt."""
        current_job = self._get_owned_processing_job(
            job_id,
            attempt_id,
        )
        updated_job = deepcopy(current_job)
        updated_job.mark_succeeded(
            result,
            finished_at=completed_at,
        )

        self._persist_owned_attempt_update(
            current_job=current_job,
            updated_job=updated_job,
            attempt_id=attempt_id,
            operation_name="complete document job",
        )

        return deepcopy(updated_job)

    def fail_job(
        self,
        job_id: str,
        attempt_id: str,
        reason: str,
        *,
        failed_at: datetime,
    ) -> DocumentJob:
        """Complete a job with a terminal failure."""
        current_job = self._get_owned_processing_job(
            job_id,
            attempt_id,
        )
        updated_job = deepcopy(current_job)
        updated_job.mark_failed(
            reason,
            finished_at=failed_at,
        )

        self._persist_owned_attempt_update(
            current_job=current_job,
            updated_job=updated_job,
            attempt_id=attempt_id,
            operation_name="fail document job",
        )

        return deepcopy(updated_job)

    def release_retryable_claim(
        self,
        job_id: str,
        attempt_id: str,
        *,
        released_at: datetime,
    ) -> DocumentJob:
        """Release processing ownership after a retryable failure."""
        current_job = self._get_owned_processing_job(
            job_id,
            attempt_id,
        )
        updated_job = deepcopy(current_job)
        updated_job.release_for_retry(
            updated_at=released_at,
        )

        self._persist_owned_attempt_update(
            current_job=current_job,
            updated_job=updated_job,
            attempt_id=attempt_id,
            operation_name="release document job claim",
        )

        return deepcopy(updated_job)

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

        elif (
            current_job.status is JobStatus.PENDING_UPLOAD and current_job.attempts >= 1
        ):
            normalized_reason = reason.strip()

            if not normalized_reason:
                raise JobStateConflictError("dead job must have an error reason")

            updated_job = DocumentJob.rehydrate(
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

        else:
            raise JobStateConflictError(
                f"job {job_id} cannot be marked dead from {current_job.status.value}"
            )

        try:
            self._table.put_item(
                Item=document_job_to_item(updated_job),
                ConditionExpression=(
                    "#status = :expected_status "
                    "AND #attempts = :expected_attempts "
                    "AND #updated_at = :expected_updated_at"
                ),
                ExpressionAttributeNames={
                    "#status": "status",
                    "#attempts": "attempts",
                    "#updated_at": "updated_at",
                },
                ExpressionAttributeValues={
                    ":expected_status": current_job.status.value,
                    ":expected_attempts": current_job.attempts,
                    ":expected_updated_at": (current_job.updated_at.isoformat()),
                },
            )
        except ClientError as error:
            if _is_conditional_check_failure(error):
                self._raise_dead_state_conflict(job_id)

            raise _repository_error(
                "failed to mark document job dead",
                error,
            ) from error

        return deepcopy(updated_job)

    def _get_required_job(
        self,
        job_id: str,
    ) -> DocumentJob:
        """Return an existing job or raise an explicit error."""
        job = self.get_job(job_id)

        if job is None:
            raise JobNotFoundError(f"job {job_id} was not found")

        return job

    def _get_owned_processing_job(
        self,
        job_id: str,
        attempt_id: str,
    ) -> DocumentJob:
        """Return a processing job owned by the expected attempt."""
        job = self._get_required_job(job_id)

        if job.status is not JobStatus.PROCESSING:
            raise JobStateConflictError(f"job {job_id} is not processing")

        active_attempt = job.active_attempt

        if active_attempt is None:
            raise JobStateConflictError("processing job has no active attempt")

        if active_attempt.attempt_id != attempt_id:
            raise JobAttemptMismatchError(
                f"attempt {attempt_id} does not own job {job_id}"
            )

        return job

    def _persist_owned_attempt_update(
        self,
        *,
        current_job: DocumentJob,
        updated_job: DocumentJob,
        attempt_id: str,
        operation_name: str,
    ) -> None:
        """Persist an attempt-owned transition conditionally."""
        try:
            self._table.put_item(
                Item=document_job_to_item(updated_job),
                ConditionExpression=(
                    "#status = :processing "
                    "AND #attempt_id = :attempt_id "
                    "AND #updated_at = :expected_updated_at"
                ),
                ExpressionAttributeNames={
                    "#status": "status",
                    "#attempt_id": "active_attempt_id",
                    "#updated_at": "updated_at",
                },
                ExpressionAttributeValues={
                    ":processing": JobStatus.PROCESSING.value,
                    ":attempt_id": attempt_id,
                    ":expected_updated_at": (current_job.updated_at.isoformat()),
                },
            )
        except ClientError as error:
            if _is_conditional_check_failure(error):
                self._raise_attempt_update_conflict(
                    current_job.job_id,
                    attempt_id,
                )

            raise _repository_error(
                f"failed to {operation_name}",
                error,
            ) from error

    def _raise_claim_conflict(
        self,
        job_id: str,
        *,
        claimed_at: datetime,
    ) -> None:
        """Translate a failed conditional claim."""
        current_job = self.get_job(job_id)

        if current_job is None:
            raise JobNotFoundError(f"job {job_id} was not found")

        if current_job.status is JobStatus.PROCESSING:
            active_attempt = current_job.active_attempt

            if active_attempt is not None and not active_attempt.is_lease_expired(
                claimed_at
            ):
                raise JobClaimConflictError(f"job {job_id} already has an active claim")

        raise JobStateConflictError(f"job {job_id} changed before it could be claimed")

    def _raise_attempt_update_conflict(
        self,
        job_id: str,
        attempt_id: str,
    ) -> None:
        """Translate a failed attempt-owned conditional update."""
        current_job = self.get_job(job_id)

        if current_job is None:
            raise JobNotFoundError(f"job {job_id} was not found")

        if current_job.status is not JobStatus.PROCESSING:
            raise JobStateConflictError(f"job {job_id} is not processing")

        active_attempt = current_job.active_attempt

        if active_attempt is None or active_attempt.attempt_id != attempt_id:
            raise JobAttemptMismatchError(
                f"attempt {attempt_id} does not own job {job_id}"
            )

        raise JobStateConflictError(f"job {job_id} changed before the update completed")

    def _raise_dead_state_conflict(
        self,
        job_id: str,
    ) -> None:
        """Translate a failed dead-state reconciliation."""
        current_job = self.get_job(job_id)

        if current_job is None:
            raise JobNotFoundError(f"job {job_id} was not found")

        raise JobStateConflictError(f"job {job_id} changed before dead reconciliation")


def _is_conditional_check_failure(
    error: ClientError,
) -> bool:
    """Return whether DynamoDB rejected a conditional operation."""
    return error.response.get("Error", {}).get("Code") == _CONDITIONAL_CHECK_FAILED


def _repository_error(
    message: str,
    error: ClientError,
) -> RepositoryError:
    """Create a normalized repository error."""
    error_code = error.response.get("Error", {}).get(
        "Code",
        "Unknown",
    )

    return RepositoryError(f"{message}: DynamoDB error {error_code}")


_repository_contract_check: DocumentJobRepository
_repository_contract_check = DynamoDBDocumentJobRepository(
    table=None,
)
