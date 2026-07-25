"""Domain-specific exceptions for CloudDoc workflows."""


class DomainError(Exception):
    """Base exception for domain rule violations."""


class InvalidDomainValueError(DomainError):
    """Raised when a domain value violates an invariant."""


class InvalidProcessingAttemptError(DomainError):
    """Raised when a processing attempt is structurally invalid."""


class InvalidStateTransitionError(DomainError):
    """Raised when a document job state transition is not allowed."""


class TerminalJobMutationError(InvalidStateTransitionError):
    """Raised when ordinary processing tries to mutate a terminal job."""
