import os
import sys
from pathlib import Path

import pytest

# Force python implementation for protobuf to stay compatible with generated files
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

# Disable console logging during tests to prevent log output from polluting
# CLI test stdout (fixes test_cli_dev_unit, test_cli_main, etc.)
# Must be set before any ming_drlms module imports that initialize logging
os.environ.setdefault("DRLMS_LOG_CONSOLE", "0")

# Ensure local src takes precedence before tests import target modules
_root = Path(__file__).resolve().parents[2]
_src_dir = _root / "src"
if str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))
_cli_src = _root / "tools" / "cli" / "src"
if str(_cli_src) not in sys.path:
    sys.path.append(str(_cli_src))


@pytest.fixture(autouse=True)
def ensure_pythonpath():
    # keep precedence during test execution as well
    root = Path(__file__).resolve().parents[2]
    src_dir = root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    cli_src = root / "tools" / "cli" / "src"
    if str(cli_src) not in sys.path:
        sys.path.append(str(cli_src))

    # Disable console logging during tests to prevent log output from
    # polluting CLI test stdout (fixes test_cli_dev_unit, test_cli_main, etc.)
    old_value = os.environ.get("DRLMS_LOG_CONSOLE")
    os.environ["DRLMS_LOG_CONSOLE"] = "0"

    yield

    # Restore original value
    if old_value is None:
        os.environ.pop("DRLMS_LOG_CONSOLE", None)
    else:
        os.environ["DRLMS_LOG_CONSOLE"] = old_value
