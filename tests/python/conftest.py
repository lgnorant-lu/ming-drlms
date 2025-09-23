import sys
from pathlib import Path

import pytest

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
    yield
