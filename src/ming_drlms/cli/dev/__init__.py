from __future__ import annotations

import typer

from . import test as _test
from . import coverage as _coverage
from . import pkg as _pkg
from . import artifacts as _artifacts


dev_app = typer.Typer(help="developer utilities (test/coverage/pkg/artifacts)")

dev_app.add_typer(_test.test_app, name="test")
dev_app.add_typer(_coverage.coverage_app, name="coverage")
dev_app.add_typer(_pkg.pkg_app, name="pkg")
dev_app.add_typer(_artifacts.artifacts_app, name="artifacts")


__all__ = ["dev_app"]
