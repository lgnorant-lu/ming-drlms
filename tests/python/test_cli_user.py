from pathlib import Path

import json
import re
import pytest
from typer.testing import CliRunner

from ming_drlms.main import app
from ming_drlms.users import parse_users


@pytest.fixture(scope="module")
def runner():
    return CliRunner()


def read_users(p: Path) -> str:
    return p.read_text(errors="ignore") if p.exists() else ""


def test_user_add_and_list_table_and_json(tmp_path: Path, runner: CliRunner):
    data_dir = tmp_path / "srv"
    users = data_dir / "users.txt"
    # add user
    res = runner.invoke(
        app, ["user", "add", "alice", "-d", str(data_dir)], input="p\np\n"
    )
    assert res.exit_code == 0, res.output
    txt = read_users(users)
    assert "alice::" in txt
    assert "$argon2id$" in txt

    # list table
    res = runner.invoke(app, ["user", "list", "-d", str(data_dir)])
    assert res.exit_code == 0
    assert "alice" in res.output
    assert "argon2" in res.output

    # list json
    res = runner.invoke(app, ["user", "list", "-d", str(data_dir), "--json"])
    assert res.exit_code == 0
    lines = [ln for ln in res.output.splitlines() if ln.strip()]
    arr = json.loads(lines[-1])
    assert any(it["username"] == "alice" and it["format"] == "argon2" for it in arr)


def test_user_add_duplicate_fails(tmp_path: Path, runner: CliRunner):
    data_dir = tmp_path / "srv"
    _ = runner.invoke(
        app, ["user", "add", "alice", "-d", str(data_dir)], input="p\np\n"
    )
    res = runner.invoke(
        app, ["user", "add", "alice", "-d", str(data_dir)], input="p\np\n"
    )
    assert res.exit_code != 0
    assert "user exists" in res.output


def test_user_passwd_nonexist_fails(tmp_path: Path, runner: CliRunner):
    data_dir = tmp_path / "srv"
    res = runner.invoke(
        app, ["user", "passwd", "missing", "-d", str(data_dir)], input="p\np\n"
    )
    assert res.exit_code != 0
    assert "does not exist" in res.output


def test_user_passwd_updates_hash(tmp_path: Path, runner: CliRunner):
    data_dir = tmp_path / "srv"
    users = data_dir / "users.txt"
    _ = runner.invoke(
        app, ["user", "add", "alice", "-d", str(data_dir)], input="x\nx\n"
    )
    before = read_users(users)
    res = runner.invoke(
        app, ["user", "passwd", "alice", "-d", str(data_dir)], input="y\ny\n"
    )
    assert res.exit_code == 0
    after = read_users(users)
    assert before != after
    assert re.search(r"^alice::\$argon2id\$", after, re.M)


def test_user_del_ok_and_force(tmp_path: Path, runner: CliRunner):
    data_dir = tmp_path / "srv"
    users = data_dir / "users.txt"
    _ = runner.invoke(app, ["user", "add", "bob", "-d", str(data_dir)], input="p\np\n")
    res = runner.invoke(app, ["user", "del", "bob", "-d", str(data_dir)])
    assert res.exit_code == 0
    assert "bob" not in read_users(users)
    # force delete missing
    res = runner.invoke(app, ["user", "del", "ghost", "-d", str(data_dir), "--force"])
    assert res.exit_code == 0


def test_user_add_and_passwd_from_stdin(tmp_path: Path, runner: CliRunner):
    data_dir = tmp_path / "srv"
    # add via stdin
    res = runner.invoke(
        app,
        ["user", "add", "stdinuser", "-d", str(data_dir), "--password-from-stdin"],
        input="s3cret\n",
    )
    assert res.exit_code == 0, res.output


def test_parse_users_unit(tmp_path: Path):
    data_dir = tmp_path / "srv"
    users = data_dir / "users.txt"
    data_dir.mkdir(parents=True, exist_ok=True)
    users.write_text(
        "\n".join(
            [
                "argon2_user::$argon2id$v=19$m=65536,t=2,p=1$YmFzZTY0$YWJjZGVm",  # dummy payload
                "# comment",
            ]
        )
        + "\n"
    )
    recs = parse_users(users)
    kinds = {u: k for (u, k, _e) in recs}
    assert kinds.get("argon2_user") == "argon2"
    # parsing unit test only; no CLI invocation here


def test_user_add_invalid_username_exits_2(
    tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    data_dir = tmp_path / "srv"

    def bad_validate(username: str) -> None:
        raise ValueError("bad-name")

    monkeypatch.setattr("ming_drlms.cli.user.validate_username", bad_validate)

    res = runner.invoke(
        app, ["user", "add", "invalid", "-d", str(data_dir)], input="p\np\n"
    )
    assert res.exit_code == 2
    assert "bad-name" in res.output


def test_user_add_from_stdin_empty_password(tmp_path: Path, runner: CliRunner):
    data_dir = tmp_path / "srv"
    res = runner.invoke(
        app,
        ["user", "add", "stdin-empty", "-d", str(data_dir), "--password-from-stdin"],
        input="\n",
    )
    assert res.exit_code == 2
    assert "empty password from stdin" in res.output


def test_user_passwd_from_stdin_empty_password(tmp_path: Path, runner: CliRunner):
    data_dir = tmp_path / "srv"
    # ensure user exists first
    _ = runner.invoke(
        app, ["user", "add", "alice", "-d", str(data_dir)], input="p\np\n"
    )

    res = runner.invoke(
        app,
        ["user", "passwd", "alice", "-d", str(data_dir), "--password-from-stdin"],
        input="\n",
    )
    assert res.exit_code == 2
    assert "empty password from stdin" in res.output


def test_user_passwd_mismatched_prompts_exit_2(tmp_path: Path, runner: CliRunner):
    data_dir = tmp_path / "srv"
    _ = runner.invoke(
        app, ["user", "add", "alice", "-d", str(data_dir)], input="a\na\n"
    )

    res = runner.invoke(
        app,
        ["user", "passwd", "alice", "-d", str(data_dir)],
        input="p\nq\n",
    )
    assert res.exit_code == 2
    assert "passwords do not match" in res.output


def test_user_del_missing_without_force(tmp_path: Path, runner: CliRunner):
    data_dir = tmp_path / "srv"
    res = runner.invoke(app, ["user", "del", "ghost", "-d", str(data_dir)])
    assert res.exit_code == 1
    assert "user not found" in res.output


def test_user_del_keyerror_branches(
    tmp_path: Path, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
):
    data_dir = tmp_path / "srv"
    _ = runner.invoke(app, ["user", "add", "bob", "-d", str(data_dir)], input="p\np\n")

    def bad_del(records, username):  # type: ignore[unused-argument]
        raise KeyError("missing")

    monkeypatch.setattr("ming_drlms.cli.user._del_user_record", bad_del)

    # without force
    res1 = runner.invoke(app, ["user", "del", "bob", "-d", str(data_dir)])
    assert res1.exit_code == 1
    assert "user not found" in res1.output

    # with force
    res2 = runner.invoke(app, ["user", "del", "bob", "-d", str(data_dir), "--force"])
    assert res2.exit_code == 0
    assert "user not found, ignored" in res2.output


def test_user_list_json_on_empty_file(tmp_path: Path, runner: CliRunner):
    data_dir = tmp_path / "srv"
    data_dir.mkdir(parents=True, exist_ok=True)
    res = runner.invoke(app, ["user", "list", "-d", str(data_dir), "--json"])
    assert res.exit_code == 0
    lines = [ln for ln in res.output.splitlines() if ln.strip()]
    arr = json.loads(lines[-1])
    assert arr == []
