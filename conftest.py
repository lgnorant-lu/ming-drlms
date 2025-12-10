"""Top-level pytest configuration for DRLMS.

This file must be at the project root per pytest's deprecation of
pytest_plugins in non-top-level conftest files.
"""

import pytest  # noqa: F401

# Enable pytest-asyncio plugin for the entire test suite
pytest_plugins = ("pytest_asyncio",)
