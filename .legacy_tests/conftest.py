"""Pytest configuration for legacy tests.

This directory contains archived tests from Phase 15 (Ed25519 / identity.json).
They are **not** meant to be collected or run as part of the normal test suite.
"""

import pathlib
from typing import Any


def pytest_ignore_collect(  # type: ignore[override]
    collection_path: pathlib.Path,
    path: Any,
    config: Any,
) -> bool:
    """Ignore all tests under tests/legacy/ by default.

    These files are kept only for historical reference and should not
    be executed in Phase 15.5+ where the underlying APIs have been removed.
    """
    try:
        return "tests" in collection_path.parts and "legacy" in collection_path.parts
    except Exception:
        return False
