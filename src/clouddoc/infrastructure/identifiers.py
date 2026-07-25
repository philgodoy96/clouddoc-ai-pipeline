"""Concrete runtime identifier generators."""

from uuid import uuid4


class UUIDJobIdGenerator:
    """Generate opaque UUID-based document job identifiers."""

    def generate(self) -> str:
        """Return a new document job identifier."""
        return f"job_{uuid4().hex}"
