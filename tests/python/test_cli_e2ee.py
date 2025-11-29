from __future__ import annotations

from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from ming_drlms.main import app
from ming_drlms.core.mproto_v2_client import AuthenticationError, MP2Error


@pytest.fixture(scope="module")
def runner() -> CliRunner:
    return CliRunner()


def _ctx_with(obj):
    class Ctx:
        def __enter__(self):
            return obj

        def __exit__(self, exc_type, exc, tb):
            return False

    return Ctx()


def test_generate_keys_success_and_nonzero(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
):
    import ming_drlms.cli.e2ee as e2ee_mod

    # success code=0
    res_ok = SimpleNamespace(code=0, message="ok", registration_id=1, pre_key_count=10)
    monkeypatch.setattr(
        e2ee_mod,
        "create_mp2_client",
        lambda *a, **k: _ctx_with(
            SimpleNamespace(e2ee_generate_keys=lambda *x, **y: res_ok)
        ),
    )
    r1 = runner.invoke(
        app, ["e2ee", "generate-keys", "--user", "alice"]
    )  # target defaults to user
    assert r1.exit_code == 0
    assert "成功" in r1.output or "code=0" in r1.output

    # nonzero code still prints and exits 0
    res_bad = SimpleNamespace(code=5, message="bad", registration_id=2, pre_key_count=0)
    monkeypatch.setattr(
        e2ee_mod,
        "create_mp2_client",
        lambda *a, **k: _ctx_with(
            SimpleNamespace(e2ee_generate_keys=lambda *x, **y: res_bad)
        ),
    )
    r2 = runner.invoke(
        app, ["e2ee", "generate-keys", "--user", "alice", "--force"]
    )  # coverage of flag
    assert r2.exit_code == 0
    assert "code=5" in r2.output and "bad" in r2.output


def test_generate_keys_errors(monkeypatch: pytest.MonkeyPatch, runner: CliRunner):
    import ming_drlms.cli.e2ee as e2ee_mod

    class EnterAuthErr:
        def __enter__(self):
            raise AuthenticationError("auth")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(e2ee_mod, "create_mp2_client", lambda *a, **k: EnterAuthErr())
    r1 = runner.invoke(
        app, ["e2ee", "generate-keys", "--user", "alice"]
    )  # AuthenticationError
    assert r1.exit_code == 1

    class EnterMP2Err:
        def __enter__(self):
            raise MP2Error("boom")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(e2ee_mod, "create_mp2_client", lambda *a, **k: EnterMP2Err())
    r2 = runner.invoke(app, ["e2ee", "generate-keys", "--user", "alice"])  # MP2Error
    assert r2.exit_code == 2

    class EnterOSError:
        def __enter__(self):
            raise OSError("net")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(e2ee_mod, "create_mp2_client", lambda *a, **k: EnterOSError())
    r3 = runner.invoke(app, ["e2ee", "generate-keys", "--user", "alice"])  # OSError
    assert r3.exit_code == 2


def test_prekey_bundle_success_and_nonzero(
    monkeypatch: pytest.MonkeyPatch, runner: CliRunner
):
    import ming_drlms.cli.e2ee as e2ee_mod

    ok_bundle = SimpleNamespace(
        code=0,
        message="ok",
        device_id=1,
        registration_id=2,
        pre_key_id=3,
        pre_key_public=b"pk",
        signed_pre_key_id=4,
        signed_pre_key_public=b"spk",
        signed_pre_key_signature=b"sig",
        identity_key=b"id",
    )
    monkeypatch.setattr(
        e2ee_mod,
        "create_mp2_client",
        lambda *a, **k: _ctx_with(
            SimpleNamespace(e2ee_fetch_prekey_bundle=lambda *x, **y: ok_bundle)
        ),
    )
    r1 = runner.invoke(
        app, ["e2ee", "prekey-bundle", "--user", "alice"]
    )  # default target
    assert r1.exit_code == 0
    assert "预密钥包" in r1.output or "device=1" in r1.output

    bad_bundle = SimpleNamespace(code=77, message="oops")
    monkeypatch.setattr(
        e2ee_mod,
        "create_mp2_client",
        lambda *a, **k: _ctx_with(
            SimpleNamespace(e2ee_fetch_prekey_bundle=lambda *x, **y: bad_bundle)
        ),
    )
    r2 = runner.invoke(
        app, ["e2ee", "prekey-bundle", "--user", "alice", "--target-user", "bob"]
    )
    assert r2.exit_code == 0  # nonzero code path exits 0 with warning
    assert "code=77" in r2.output and "oops" in r2.output


def test_prekey_bundle_errors(monkeypatch: pytest.MonkeyPatch, runner: CliRunner):
    import ming_drlms.cli.e2ee as e2ee_mod

    class EnterAuthErr:
        def __enter__(self):
            raise AuthenticationError("auth")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(e2ee_mod, "create_mp2_client", lambda *a, **k: EnterAuthErr())
    r1 = runner.invoke(
        app, ["e2ee", "prekey-bundle", "--user", "alice"]
    )  # AuthenticationError
    assert r1.exit_code == 1

    class EnterMP2Err:
        def __enter__(self):
            raise MP2Error("boom")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(e2ee_mod, "create_mp2_client", lambda *a, **k: EnterMP2Err())
    r2 = runner.invoke(app, ["e2ee", "prekey-bundle", "--user", "alice"])  # MP2Error
    assert r2.exit_code == 2

    class EnterOSError:
        def __enter__(self):
            raise OSError("net")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(e2ee_mod, "create_mp2_client", lambda *a, **k: EnterOSError())
    r3 = runner.invoke(app, ["e2ee", "prekey-bundle", "--user", "alice"])  # OSError
    assert r3.exit_code == 2
