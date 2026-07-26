"""Concrete runtime identifier generators."""

from uuid import uuid4


class UUIDJobIdGenerator:
    """Generate opaque UUID-based document job identifiers."""

    def generate(self) -> str:
        """Return a new document job identifier."""
        return f"job_{uuid4().hex}"


class UUIDProcessingAttemptIdGenerator:
    """Generate opaque UUID-based processing-attempt identifiers."""

    def generate(self) -> str:
        """Return a new processing-attempt identifier."""
        return f"attempt_{uuid4().hex}"
