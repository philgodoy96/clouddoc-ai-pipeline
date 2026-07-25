"""Workflow correlation identifiers."""

from dataclasses import dataclass

from clouddoc.domain.errors import InvalidDomainValueError


@dataclass(frozen=True, slots=True)
class CorrelationContext:
    """Identifiers used to trace a workflow and its originating request."""

    request_id: str
    correlation_id: str

    def __post_init__(self) -> None:
        """Validate correlation identifiers."""
        if not self.request_id.strip():
            raise InvalidDomainValueError("request_id must not be empty")

        if not self.correlation_id.strip():
            raise InvalidDomainValueError("correlation_id must not be empty")
