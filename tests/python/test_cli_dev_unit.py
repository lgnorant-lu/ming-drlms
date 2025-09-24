from __future__ import annotations

from typer.testing import CliRunner

from ming_drlms.main import app


def test_dev_pkg_help():
    runner = CliRunner()
    res = runner.invoke(app, ["dev", "pkg", "--help"])  # noqa: E501
    assert res.exit_code == 0
    assert "package" in res.output.lower()


def test_dev_coverage_help():
    runner = CliRunner()
    res = runner.invoke(app, ["dev", "coverage", "--help"])  # noqa: E501
    assert res.exit_code == 0


def test_dev_artifacts_help():
    runner = CliRunner()
    res = runner.invoke(app, ["dev", "artifacts", "--help"])  # noqa: E501
    assert res.exit_code == 0


def test_dev_pkg_build_parsing(monkeypatch):
    # Avoid actually running make
    import subprocess as sp

    class P:
        returncode = 0

    monkeypatch.setattr(sp, "run", lambda *a, **k: P())
    runner = CliRunner()
    res = runner.invoke(app, ["dev", "pkg", "build"])
    assert res.exit_code == 0


def test_dev_coverage_run_parsing(monkeypatch):
    import subprocess as sp

    class P:
        returncode = 0

    monkeypatch.setattr(sp, "run", lambda *a, **k: P())
    runner = CliRunner()
    res = runner.invoke(app, ["dev", "coverage", "run"])
    assert res.exit_code == 0


def test_dev_artifacts_collect_parsing(monkeypatch, tmp_path):
    # monkeypatch tar/process to avoid heavy work
    from ming_drlms.cli.dev import artifacts as art

    monkeypatch.setattr(art, "gather_metadata", lambda: "k=v\n")
    # use temp out
    runner = CliRunner()
    res = runner.invoke(app, ["dev", "artifacts", "artifacts", "--out", str(tmp_path)])
    assert res.exit_code == 0
