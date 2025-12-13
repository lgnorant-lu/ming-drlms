from __future__ import annotations

from pathlib import Path

import pytest

# Ensure src importable
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms import users


def test_parse_users_various_formats(tmp_path: Path) -> None:
    content = "\n".join(
        [
            "# comment line",
            "alice::$argon2id$encoded",
            "weird:stuff:not-hash",
            "plainonly",
            "",
        ]
    )
    path = tmp_path / "users.txt"
    path.write_text(content + "\r\n", encoding="utf-8")

    records = users.parse_users(path)

    assert records[0] == ("alice", "argon2", "$argon2id$encoded")
    assert records[1] == ("weird", "unknown", "stuff:not-hash")
    assert records[2] == ("plainonly", "unknown", "")


def test_parse_users_missing_file_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "missing.txt"
    assert users.parse_users(path) == []


def test_read_auth_params_from_env_defaults_and_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in [
        "DRLMS_ARGON2_T_COST",
        "DRLMS_ARGON2_M_COST",
        "DRLMS_ARGON2_PARALLELISM",
    ]:
        monkeypatch.delenv(name, raising=False)

    params = users.read_auth_params_from_env()
    assert params["time_cost"] == 2
    assert params["memory_cost"] == 65536
    assert params["parallelism"] == 1

    monkeypatch.setenv("DRLMS_ARGON2_T_COST", "3")
    monkeypatch.setenv("DRLMS_ARGON2_M_COST", "1024")
    monkeypatch.setenv("DRLMS_ARGON2_PARALLELISM", "4")

    params2 = users.read_auth_params_from_env()
    assert params2["time_cost"] == 3
    assert params2["memory_cost"] == 1024
    assert params2["parallelism"] == 4

    # Invalid values fall back to defaults
    monkeypatch.setenv("DRLMS_ARGON2_T_COST", "not-an-int")
    params3 = users.read_auth_params_from_env()
    assert params3["time_cost"] == 2


def test_generate_argon2id_hash_uses_argon2(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {}

    def fake_hash_secret(password, salt, **kwargs):  # type: ignore[override]
        called["password"] = password
        called["salt"] = salt
        called["kwargs"] = kwargs
        return b"$argon2id$dummy"

    monkeypatch.setattr(users.argon2_ll, "hash_secret", fake_hash_secret)

    h = users.generate_argon2id_hash(
        "pw",
        time_cost=2,
        memory_cost=1024,
        parallelism=1,
        hash_len=16,
        salt_len=8,
    )
    assert h == "$argon2id$dummy"
    assert called["password"] == b"pw"


def test_write_users_atomic_writes_all_kinds(tmp_path: Path) -> None:
    path = tmp_path / "users.txt"
    records = [
        ("alice", "argon2", "$argon2id$aaa"),
        ("weird", "unknown", "RIGHT"),
        ("empty", "unknown", ""),
    ]

    users.write_users_atomic(path, records)
    text = path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln]

    assert "alice::$argon2id$aaa" in lines
    assert any(ln.startswith("# unknown-format weird RIGHT") for ln in lines)
    assert any(ln.strip() == "# unknown-format empty" for ln in lines)


def test_validate_username_and_add_set_del_user() -> None:
    # validate_username
    users.validate_username("ok_user-1")
    with pytest.raises(ValueError):
        users.validate_username("")
    with pytest.raises(ValueError):
        users.validate_username("bad space")
    with pytest.raises(ValueError):
        users.validate_username("x" * 33)

    # add_user
    records: list[tuple[str, str, str]] = []
    rec2 = users.add_user(records, "alice", "enc1")
    assert ("alice", "argon2", "enc1") in rec2
    assert records == []  # original list not mutated
    with pytest.raises(KeyError):
        users.add_user(rec2, "alice", "enc2")

    # set_password
    rec3 = users.set_password(rec2, "alice", "enc2")
    assert rec3[-1] == ("alice", "argon2", "enc2")
    with pytest.raises(KeyError):
        users.set_password(rec2, "bob", "x")

    # del_user
    rec4 = users.del_user(rec3, "alice")
    assert rec4 == []
    with pytest.raises(KeyError):
        users.del_user(rec3, "bob")
