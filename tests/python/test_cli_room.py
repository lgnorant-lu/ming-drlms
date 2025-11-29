from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ming_drlms.main import app


@pytest.fixture(scope="module")
def runner() -> CliRunner:
    return CliRunner()


def _evt(**kwargs):
    return SimpleNamespace(**kwargs)


def _ctx_with(obj):
    class Ctx:
        def __enter__(self):
            return obj

        def __exit__(self, exc_type, exc, tb):
            return False

    return Ctx()


def test_room_sub_prints_members_and_events(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
):
    import ming_drlms.cli.room as room_mod

    # Fake room_service with members + events
    class FakeRS:
        def get_room_members_mp2(self, **kwargs):  # type: ignore[override]
            return [
                SimpleNamespace(user_id="alice", device_id=1),
                SimpleNamespace(user_id="bob", device_id=2),
            ]

        def subscribe(self, **kwargs):  # type: ignore[override]
            # presence join, presence leave, text, binary
            yield _evt(
                event_id=1,
                display_token="alice",
                kind=2,
                presence={"user_id": "bob"},
                payload=b"",
            )
            yield _evt(
                event_id=2,
                display_token="alice",
                kind=3,
                presence={"user_id": "bob"},
                payload=b"",
            )
            yield _evt(
                event_id=3,
                display_token="carol",
                kind=None,
                presence=None,
                payload=b"hello",
            )
            yield _evt(
                event_id=4,
                display_token="dave",
                kind=None,
                presence=None,
                payload=b"\xff\x00",
            )

    monkeypatch.setattr(room_mod, "room_service", FakeRS())

    res = runner.invoke(
        app, ["room", "sub", "--room", "demo", "--limit", "4"]
    )  # stop after 4 events
    assert res.exit_code == 0
    out = res.output
    assert "当前房间成员" in out or "房间 'demo' 目前没有其他成员" in out
    # presence messages
    assert "加入了房间" in out and "离开了房间" in out
    # text + binary fallback
    assert "hello" in out and "binary" in out


def test_room_sub_member_list_error_is_warning(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
):
    import ming_drlms.cli.room as room_mod
    from ming_drlms.cli.services.room_service import RoomServiceError

    class FakeRS:
        def get_room_members_mp2(self, **kwargs):  # type: ignore[override]
            raise RoomServiceError("member-error")

        def subscribe(self, **kwargs):  # type: ignore[override]
            # yield a single event so command returns quickly via limit
            yield _evt(
                event_id=1, display_token="a", kind=None, presence=None, payload=b"x"
            )

    monkeypatch.setattr(room_mod, "room_service", FakeRS())

    res = runner.invoke(
        app, ["room", "sub", "--room", "demo", "--limit", "1"]
    )  # coverage of warning
    assert res.exit_code == 0
    assert "无法获取成员列表" in res.output


def test_room_sub_errors_map_to_exit_codes(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
):
    import ming_drlms.cli.room as room_mod
    from ming_drlms.cli.services.room_service import RoomServiceError

    class ErrRS:
        def get_room_members_mp2(self, **kwargs):  # type: ignore[override]
            return []

        def subscribe(self, **kwargs):  # type: ignore[override]
            raise RoomServiceError("broken")

    monkeypatch.setattr(room_mod, "room_service", ErrRS())
    r1 = runner.invoke(
        app, ["room", "sub", "--room", "demo", "--limit", "1"]
    )  # RoomServiceError -> exit 1
    assert r1.exit_code == 1

    class OSErrRS:
        def get_room_members_mp2(self, **kwargs):  # type: ignore[override]
            return []

        def subscribe(self, **kwargs):  # type: ignore[override]
            raise OSError("net")

    monkeypatch.setattr(room_mod, "room_service", OSErrRS())
    r2 = runner.invoke(
        app, ["room", "sub", "--room", "demo", "--limit", "1"]
    )  # OSError -> exit 2
    assert r2.exit_code == 2


def test_room_pub_text_and_file_and_invalid(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner, tmp_path: Path
):
    import ming_drlms.cli.room as room_mod
    from ming_drlms.cli.services.room_service import PublishResult, RoomServiceError

    calls = {"publish": [], "publish_file": []}

    class FakeRS:
        def publish(self, **kwargs):  # type: ignore[override]
            calls["publish"].append(kwargs)
            return PublishResult(
                bytes_sent=len(kwargs.get("payload", b"")),
                ephemeral=bool(kwargs.get("ephemeral")),
            )

        def publish_file(self, **kwargs):  # type: ignore[override]
            calls["publish_file"].append(kwargs)
            return PublishResult(
                bytes_sent=123, ephemeral=bool(kwargs.get("ephemeral"))
            )

    monkeypatch.setattr(room_mod, "room_service", FakeRS())

    # invalid selection -> exit 2
    r_bad = runner.invoke(
        app, ["room", "pub", "--room", "demo"]
    )  # none of sources selected
    assert r_bad.exit_code == 2

    # text path
    r_text = runner.invoke(
        app, ["room", "pub", "--room", "demo", "--text", "hello", "--ephemeral"]
    )
    assert r_text.exit_code == 0
    assert any(k["room"] == "demo" and k["ephemeral"] is True for k in calls["publish"])

    # file path
    f = tmp_path / "x.txt"
    f.write_text("content", encoding="utf-8")
    r_file = runner.invoke(app, ["room", "pub", "--room", "demo", "--file", str(f)])
    assert r_file.exit_code == 0
    assert any(k["room"] == "demo" for k in calls["publish_file"])

    # service error on file path
    class BadRS(FakeRS):
        def publish_file(self, **kwargs):  # type: ignore[override]
            raise RoomServiceError("boom")

    monkeypatch.setattr(room_mod, "room_service", BadRS())
    r_err = runner.invoke(app, ["room", "pub", "--room", "demo", "--file", str(f)])
    assert r_err.exit_code == 1


def test_room_info_json_and_error(monkeypatch: pytest.MonkeyPatch, runner: CliRunner):
    import ming_drlms.cli.room as room_mod
    from ming_drlms.cli.services.room_service import RoomInfo, RoomServiceError

    class FakeRS:
        def fetch_info(self, **kwargs):  # type: ignore[override]
            return RoomInfo(
                name="r",
                details={"policy": 0, "storage_policy": 1, "owner": "alice"},
                raw=["..."],
            )

    monkeypatch.setattr(room_mod, "room_service", FakeRS())
    r_json = runner.invoke(app, ["room", "info", "--room", "r", "--json"])
    assert r_json.exit_code == 0
    assert '"owner": ' in r_json.output

    class BadRS(FakeRS):
        def fetch_info(self, **kwargs):  # type: ignore[override]
            raise RoomServiceError("bad")

    monkeypatch.setattr(room_mod, "room_service", BadRS())
    r_err = runner.invoke(app, ["room", "info", "--room", "r"])
    assert r_err.exit_code == 2


def test_room_create_ephemeral_and_error(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
):
    import ming_drlms.cli.room as room_mod
    from ming_drlms.cli.services.room_service import RoomServiceError

    class FakeRS:
        def create_room(self, **kwargs):  # type: ignore[override]
            return {"ok": True}

    monkeypatch.setattr(room_mod, "room_service", FakeRS())
    r_ok = runner.invoke(app, ["room", "create", "--room", "r", "--ephemeral"])
    assert r_ok.exit_code == 0
    assert "created" in r_ok.output or "✓" in r_ok.output

    class BadRS(FakeRS):
        def create_room(self, **kwargs):  # type: ignore[override]
            raise RoomServiceError("oops")

    monkeypatch.setattr(room_mod, "room_service", BadRS())
    r_err = runner.invoke(app, ["room", "create", "--room", "r"])
    assert r_err.exit_code == 1


def test_room_set_policy_success_and_invalid_and_error(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    import ming_drlms.cli.room as room_mod
    from ming_drlms.cli.services.room_service import RoomServiceError

    calls: list[dict] = []

    class FakeRS:
        def set_policy(self, **kwargs):  # type: ignore[override]
            calls.append(kwargs)

    monkeypatch.setattr(room_mod, "room_service", FakeRS())

    # success path with valid policy
    r_ok = runner.invoke(
        app,
        ["room", "set-policy", "--room", "r", "--policy", "retain"],
    )
    assert r_ok.exit_code == 0
    assert calls and calls[-1]["room"] == "r"
    assert calls[-1]["policy"] == "retain"

    # invalid policy -> exit 2 and error message
    r_bad = runner.invoke(
        app,
        ["room", "set-policy", "--room", "r", "--policy", "invalid"],
    )
    assert r_bad.exit_code == 2
    assert "unknown policy" in r_bad.output

    # service error -> exit 1
    class ErrRS(FakeRS):
        def set_policy(self, **kwargs):  # type: ignore[override]
            raise RoomServiceError("boom-policy-cli")

    monkeypatch.setattr(room_mod, "room_service", ErrRS())
    r_err = runner.invoke(
        app,
        ["room", "set-policy", "--room", "r", "--policy", "retain"],
    )
    assert r_err.exit_code == 1
    assert "boom-policy-cli" in r_err.output


def test_room_set_storage_policy_success_and_invalid_and_error(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    import ming_drlms.cli.room as room_mod
    from ming_drlms.cli.services.room_service import RoomServiceError

    calls: list[dict] = []

    class FakeRS:
        def set_storage_policy(self, **kwargs):  # type: ignore[override]
            calls.append(kwargs)

    monkeypatch.setattr(room_mod, "room_service", FakeRS())

    # success path with valid storage policy
    r_ok = runner.invoke(
        app,
        [
            "room",
            "set-storage-policy",
            "--room",
            "r",
            "--policy",
            "ephemeral",
        ],
    )
    assert r_ok.exit_code == 0
    assert calls and calls[-1]["room"] == "r"
    assert calls[-1]["policy"] == "ephemeral"

    # invalid storage policy -> exit 2
    r_bad = runner.invoke(
        app,
        [
            "room",
            "set-storage-policy",
            "--room",
            "r",
            "--policy",
            "invalid",
        ],
    )
    assert r_bad.exit_code == 2
    assert "unknown storage policy" in r_bad.output

    # service error -> exit 1
    class ErrRS(FakeRS):
        def set_storage_policy(self, **kwargs):  # type: ignore[override]
            raise RoomServiceError("boom-storage-cli")

    monkeypatch.setattr(room_mod, "room_service", ErrRS())
    r_err = runner.invoke(
        app,
        [
            "room",
            "set-storage-policy",
            "--room",
            "r",
            "--policy",
            "ephemeral",
        ],
    )
    assert r_err.exit_code == 1
    assert "boom-storage-cli" in r_err.output
