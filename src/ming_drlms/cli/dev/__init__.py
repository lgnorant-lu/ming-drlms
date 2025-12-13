from __future__ import annotations

import typer

from . import test as _test
from . import coverage as _coverage
from . import pkg as _pkg
from . import artifacts as _artifacts


dev_app = typer.Typer(
    help="开发者工具 (test/coverage/pkg/artifacts)",
    context_settings={"help_option_names": ["-h", "--help"]},
)

dev_app.add_typer(_test.test_app, name="test")
dev_app.add_typer(_coverage.coverage_app, name="coverage")
dev_app.add_typer(_pkg.pkg_app, name="pkg")
dev_app.add_typer(_artifacts.artifacts_app, name="artifacts")


__all__ = ["dev_app"]
