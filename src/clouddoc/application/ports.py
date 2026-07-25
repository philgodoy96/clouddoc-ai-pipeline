"""Application-layer ports for time and identity generation."""

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Provide the current application time."""

    def now(self) -> datetime:
        """Return the current timezone-aware UTC datetime."""
        ...


@runtime_checkable
class JobIdGenerator(Protocol):
    """Generate document job identifiers."""

    def generate(self) -> str:
        """Return a new document job identifier."""
        ...
