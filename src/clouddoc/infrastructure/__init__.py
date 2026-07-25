"""Concrete infrastructure adapters used at runtime."""

from clouddoc.infrastructure.clock import SystemClock
from clouddoc.infrastructure.identifiers import UUIDJobIdGenerator

__all__ = [
    "SystemClock",
    "UUIDJobIdGenerator",
]
