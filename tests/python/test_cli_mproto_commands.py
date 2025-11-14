from __future__ import annotations

from pathlib import Path
from typing import List

import pytest
from typer.testing import CliRunner

from ming_drlms.main import app
from ming_drlms.core.mproto_v2_client import AuthenticationError, RoomEvent
from ming_drlms.cli.services import PublishResult
from ming_drlms.core.token_store import TokenRecord


class _MembersStubMixin:
    def get_room_members_mp2(self, **kwargs):  # type: ignore[no-untyped-def]
        return []


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def test_cli_login_success(monkeypatch, tmp_path: Path, runner: CliRunner):
    record = TokenRecord(
        username="alice",
        host="127.0.0.1",
        port=9000,
        access_token="token",
        access_expires_at=10_000_000.0,
        refresh_token="refresh",
    )

    def fake_login_flow(host, port, username, **kwargs):  # noqa: ANN001
        return record

    monkeypatch.setattr("ming_drlms.cli.login_flow", fake_login_flow)
    token_path = tmp_path / "tokens.json"
    result = runner.invoke(
        app,
        [
            "login",
            "--user",
            "alice",
            "--host",
            "127.0.0.1",
            "--port",
            "9000",
            "--token-store",
            str(token_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "login succeeded" in result.output
    assert str(token_path) in result.output


def test_cli_login_auth_failure(monkeypatch, runner: CliRunner):
    def fake_login_flow(host, port, username, **kwargs):  # noqa: ANN001
        raise AuthenticationError("invalid credentials")

    monkeypatch.setattr("ming_drlms.cli.login_flow", fake_login_flow)
    result = runner.invoke(app, ["login", "--user", "alice"])
    assert result.exit_code == 1
    assert "login failed" in result.output


def test_room_pub_uses_mp2_client(monkeypatch, runner: CliRunner):
    calls: List[tuple[str, str, bytes, bool]] = []

    class StubService:
        def publish(self, **kwargs):
            calls.append(
                (
                    kwargs["user"],
                    kwargs["room"],
                    kwargs["payload"],
                    kwargs["ephemeral"],
                )
            )
            return PublishResult(
                bytes_sent=len(kwargs["payload"]), ephemeral=kwargs["ephemeral"]
            )

    monkeypatch.setattr("ming_drlms.cli.room.room_service", StubService())
    result = runner.invoke(
        app,
        [
            "room",
            "pub",
            "--room",
            "demo",
            "--user",
            "alice",
            "--text",
            "hello",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls == [("alice", "demo", b"hello", False)]
    assert "published" in result.output


def test_room_pub_requires_payload(runner: CliRunner):
    result = runner.invoke(app, ["room", "pub", "--room", "demo", "--user", "alice"])
    assert result.exit_code == 2
    assert "请使用" in result.output


def test_room_sub_limit(monkeypatch, runner: CliRunner):
    events = [
        RoomEvent(room_name="demo", event_id=1, payload=b"hi", display_token="t1"),
        RoomEvent(room_name="demo", event_id=2, payload=b"bye", display_token="t2"),
    ]

    class StubService(_MembersStubMixin):
        def subscribe(self, **kwargs):
            yield from events

    monkeypatch.setattr("ming_drlms.cli.room.room_service", StubService())
    result = runner.invoke(
        app,
        [
            "room",
            "sub",
            "--room",
            "demo",
            "--user",
            "alice",
            "--limit",
            "2",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "[1]" in result.output
