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
    arr = json.loads(res.output)
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


def test_list_legacy_entries_are_detected(tmp_path: Path, runner: CliRunner):
    data_dir = tmp_path / "srv"
    users = data_dir / "users.txt"
    data_dir.mkdir(parents=True, exist_ok=True)
    users.write_text(
        "alice:abcd:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n"
    )
    res = runner.invoke(app, ["user", "list", "-d", str(data_dir), "--json"])
    assert res.exit_code == 0
    arr = json.loads(res.output)
    # Jules case: must recognize legacy format
    assert any(it["username"] == "alice" and it["format"] == "legacy" for it in arr)


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
                "legacy_user:abcd:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "argon2_user::$argon2id$v=19$m=65536,t=2,p=1$YmFzZTY0$YWJjZGVm",  # dummy payload
                "# comment",
            ]
        )
        + "\n"
    )
    recs = parse_users(users)
    kinds = {u: k for (u, k, _e) in recs}
    assert kinds.get("legacy_user") == "legacy"
    assert kinds.get("argon2_user") == "argon2"
    # parsing unit test only; no CLI invocation here


def test_list_legacy_with_spaces_is_detected(tmp_path: Path, runner: CliRunner):
    data_dir = tmp_path / "srv"
    users = data_dir / "users.txt"
    data_dir.mkdir(parents=True, exist_ok=True)
    # 64-hex sha
    sha = "0123456789abcdef" * 4
    users.write_text(f"   legacy_user_ws : some_salt : {sha}   \n")
    res = runner.invoke(app, ["user", "list", "-d", str(data_dir), "--json"])
    assert res.exit_code == 0
    arr = json.loads(res.output)
    assert any(
        it["username"] == "legacy_user_ws" and it["format"] == "legacy" for it in arr
    )


def test_list_legacy_with_crlf_is_detected(tmp_path: Path, runner: CliRunner):
    data_dir = tmp_path / "srv"
    users = data_dir / "users.txt"
    data_dir.mkdir(parents=True, exist_ok=True)
    sha = "abcdef0123456789" * 4
    # Write CRLF line ending explicitly
    users.write_bytes(f"legacy_user_crlf:salt:{sha}\r\n".encode("utf-8"))
    res = runner.invoke(app, ["user", "list", "-d", str(data_dir), "--json"])
    assert res.exit_code == 0
    arr = json.loads(res.output)
    assert any(
        it["username"] == "legacy_user_crlf" and it["format"] == "legacy" for it in arr
    )
