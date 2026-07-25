"""Tests for the initial Python package foundation."""

import clouddoc


def test_package_can_be_imported() -> None:
    """The application package should be importable after installation."""
    assert clouddoc.__doc__ == "CloudDoc AI Pipeline application package."
