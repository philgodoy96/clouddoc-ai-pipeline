"""Application-layer errors."""

from typing import Any


class ApplicationError(Exception):
    """Base error for application service failures."""


class ApplicationConflictError(ApplicationError):
    """Raised when an application operation conflicts with existing state."""


class ApplicationNotFoundError(ApplicationError):
    """Raised when a requested application resource does not exist."""


class ApplicationDependencyError(ApplicationError):
    """Raised when an application dependency cannot complete an operation."""

    def __init__(
        self,
        message: str,
        *,
        cause: Exception | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialize a dependency failure with optional context."""
        super().__init__(message)
        self.cause = cause
        self.context = dict(context or {})
