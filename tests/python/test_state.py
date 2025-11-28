from __future__ import annotations

import json
import sys
from pathlib import Path as _P, Path

import pytest

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

import ming_drlms.state as st


def test_load_state_creates_default_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(st, "STATE_DIR", tmp_path, raising=False)
    monkeypatch.setattr(st, "STATE_PATH", tmp_path / "state.json", raising=False)

    state = st.load_state()
    assert state == {"profiles": {}, "rooms": {}}
    assert (tmp_path).is_dir()


def test_load_state_invalid_json_and_non_dict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(st, "STATE_DIR", tmp_path, raising=False)
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(st, "STATE_PATH", state_path, raising=False)

    # Invalid JSON
    state_path.write_text("not-json", encoding="utf-8")
    state1 = st.load_state()
    assert state1 == {"profiles": {}, "rooms": {}}

    # Non-dict root
    state_path.write_text("[]", encoding="utf-8")
    state2 = st.load_state()
    assert state2 == {"profiles": {}, "rooms": {}}


def test_load_state_fills_missing_profiles_and_rooms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(st, "STATE_DIR", tmp_path, raising=False)
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(st, "STATE_PATH", state_path, raising=False)

    state_path.write_text(json.dumps({"foo": 1}), encoding="utf-8")
    state = st.load_state()
    assert state["foo"] == 1
    assert "profiles" in state and isinstance(state["profiles"], dict)
    assert "rooms" in state and isinstance(state["rooms"], dict)


def test_save_state_writes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(st, "STATE_DIR", tmp_path, raising=False)
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(st, "STATE_PATH", state_path, raising=False)

    data = {"profiles": {"p": {}}, "rooms": {}}
    st.save_state(data)

    assert state_path.exists()
    loaded = json.loads(state_path.read_text(encoding="utf-8"))
    assert loaded == data


def test_save_state_swallows_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(st, "STATE_DIR", tmp_path, raising=False)
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(st, "STATE_PATH", state_path, raising=False)

    def bad_write_text(self, content):  # type: ignore[override]
        raise RuntimeError("boom")

    monkeypatch.setattr(Path, "write_text", bad_write_text, raising=False)

    # Should not raise
    st.save_state({"profiles": {}, "rooms": {}})


def test_get_last_event_id_variants() -> None:
    # Valid int
    state = {"rooms": {"k": {"last_event_id": 5}}}
    assert st.get_last_event_id(state, "k") == 5

    # Numeric string
    state = {"rooms": {"k": {"last_event_id": "7"}}}
    assert st.get_last_event_id(state, "k") == 7

    # Non-numeric, wrong types, or missing -> 0
    state = {"rooms": {"k": {"last_event_id": "x"}}}
    assert st.get_last_event_id(state, "k") == 0
    state = {"rooms": {"k": {"last_event_id": None}}}
    assert st.get_last_event_id(state, "k") == 0
    state = {"rooms": {}}
    assert st.get_last_event_id(state, "k") == 0


def test_set_last_event_id_creates_and_updates() -> None:
    state: dict = {}
    st.set_last_event_id(state, "k", 10)
    assert state["rooms"]["k"]["last_event_id"] == 10

    # Smaller event_id should not overwrite
    st.set_last_event_id(state, "k", 5)
    assert state["rooms"]["k"]["last_event_id"] == 10

    # Larger should overwrite
    st.set_last_event_id(state, "k", 20)
    assert state["rooms"]["k"]["last_event_id"] == 20
