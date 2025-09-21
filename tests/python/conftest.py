import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def ensure_pythonpath():
    # ensure tools/cli/src is importable when running tests directly
    root = Path(__file__).resolve().parents[2]
    cli_src = root / "tools" / "cli" / "src"
    if str(cli_src) not in sys.path:
        sys.path.insert(0, str(cli_src))
    yield
