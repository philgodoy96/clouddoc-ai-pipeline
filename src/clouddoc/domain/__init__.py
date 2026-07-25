"""Core domain models and invariants for CloudDoc workflows."""

from clouddoc.domain.correlation_context import CorrelationContext
from clouddoc.domain.document_job import DocumentJob
from clouddoc.domain.errors import (
    DomainError,
    InvalidDomainValueError,
    InvalidProcessingAttemptError,
    InvalidStateTransitionError,
    TerminalJobMutationError,
)
from clouddoc.domain.job_status import JobStatus
from clouddoc.domain.processing_attempt import ProcessingAttempt
from clouddoc.domain.state_transitions import is_transition_allowed

__all__ = [
    "CorrelationContext",
    "DocumentJob",
    "DomainError",
    "InvalidDomainValueError",
    "InvalidProcessingAttemptError",
    "InvalidStateTransitionError",
    "JobStatus",
    "ProcessingAttempt",
    "TerminalJobMutationError",
    "is_transition_allowed",
]
