from pathlib import Path

import pytest
from typer.testing import CliRunner

from ming_drlms.main import app


@pytest.fixture(scope="module")
def runner():
    return CliRunner()


def test_server_up_down_status(runner, tmp_path: Path):
    # choose a non-default port to avoid clashes
    port = 8099
    data_dir = tmp_path / "srv"
    result = runner.invoke(
        app, ["server-up", "-p", str(port), "-d", str(data_dir), "--no-strict"]
    )  # noqa: E501
    assert result.exit_code in (0, None)

    # status should show listening yes
    result = runner.invoke(app, ["server-status", "-p", str(port)])
    assert result.exit_code == 0

    # down should succeed
    result = runner.invoke(app, ["server-down"])
    assert result.exit_code == 0

    # server-status when not running
    result = runner.invoke(app, ["server-status", "-p", str(port)])
    assert result.exit_code == 0


def test_client_argument_errors(runner):
    # upload without file
    result = runner.invoke(app, ["client", "upload"])  # missing arg
    assert result.exit_code != 0

    # server-up with invalid port
    result = runner.invoke(
        app, ["server-up", "--port", "not-a-port"], catch_exceptions=True
    )  # noqa: E501
    assert result.exit_code != 0


def test_space_send_validation(runner):
    # both or none of --text/--file should error
    result = runner.invoke(app, ["space", "send", "-r", "roomx"], catch_exceptions=True)  # noqa: E501
    assert result.exit_code != 0


def test_space_history_cli_parsing(runner):
    # only CLI argument parsing path; network mocked by unreachable port
    result = runner.invoke(
        app,
        [
            "space",
            "history",
            "-r",
            "r1",
            "-n",
            "5",
            "-s",
            "0",
            "-H",
            "127.0.0.1",
            "-p",
            "65500",
        ],
        catch_exceptions=True,
    )
    assert result.exit_code != 0


def test_server_logs_when_no_log_file(runner, tmp_path: Path):
    # ensure log file missing and command returns gracefully
    result = runner.invoke(app, ["server-logs", "-n", "5"])  # no server started
    assert result.exit_code == 0


def test_config_init_overwrite(tmp_path: Path, runner):
    cfg = tmp_path / "drlms.yaml"
    # first time writes template
    result = runner.invoke(app, ["config", "init", "--path", str(cfg)])
    assert result.exit_code == 0
    # run again to ensure idempotency (should still exit 0)
    result = runner.invoke(app, ["config", "init", "--path", str(cfg)])
    assert result.exit_code == 0


def test_space_leave_parsing_error(runner):
    # missing room argument should fail before network
    result = runner.invoke(app, ["space", "leave"], catch_exceptions=True)
    assert result.exit_code != 0


def test_cli_version_option(runner):
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "ming-drlms CLI version:" in result.output


def test_cli_version_short_option(runner):
    result = runner.invoke(app, ["-V"])  # alias for --version
    assert result.exit_code == 0
    assert "ming-drlms CLI version:" in result.output


def test_user_list_help_contains_examples(runner):
    result = runner.invoke(app, ["user", "list", "--help"])
    assert result.exit_code == 0
    assert "Examples:" in result.output


def test_teaching_help_show_user(runner):
    # Even if packaged md is missing in test env, command should succeed
    result = runner.invoke(app, ["help", "show", "user"])
    assert result.exit_code == 0


def test_dev_group_registered_and_help(runner):
    # dev group should be present and show help without error
    result = runner.invoke(app, ["dev", "--help"])
    assert result.exit_code == 0
    assert "developer utilities" in result.output.lower()


def test_help_topics_include_dev(runner):
    result = runner.invoke(app, ["help", "show", "dev"])
    assert result.exit_code == 0


def test_update_check_throttled_and_nonblocking(monkeypatch, runner):
    # Force throttle by setting env to disable update check
    monkeypatch.setenv("DRLMS_UPDATE_CHECK", "0")
    # Call a harmless command
    result = runner.invoke(app, ["server-status", "-p", "65500"])  # port likely closed
    assert result.exit_code == 0
    # No exception and no forced output required
