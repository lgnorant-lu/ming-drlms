import json
from pathlib import Path
from typing import Dict, Any

STATE_DIR = Path.home() / ".drlms"
STATE_PATH = STATE_DIR / "state.json"


def _ensure_dirs() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def load_state() -> Dict[str, Any]:
    _ensure_dirs()
    if not STATE_PATH.exists():
        return {"profiles": {}, "rooms": {}}
    try:
        data = json.loads(STATE_PATH.read_text(errors="ignore") or "{}")
        if not isinstance(data, dict):
            return {"profiles": {}, "rooms": {}}
        data.setdefault("profiles", {})
        data.setdefault("rooms", {})
        return data
    except Exception:
        return {"profiles": {}, "rooms": {}}


def save_state(state: Dict[str, Any]) -> None:
    _ensure_dirs()
    try:
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    except Exception:
        pass


def get_last_event_id(state: Dict[str, Any], key: str) -> int:
    try:
        val = state.get("rooms", {}).get(key, {}).get("last_event_id", 0)
        return (
            int(val)
            if isinstance(val, int) or (isinstance(val, str) and val.isdigit())
            else 0
        )
    except Exception:
        return 0


def set_last_event_id(state: Dict[str, Any], key: str, event_id: int) -> None:
    rooms = state.setdefault("rooms", {})
    entry = rooms.setdefault(key, {})
    if int(entry.get("last_event_id", 0)) < int(event_id):
        entry["last_event_id"] = int(event_id)
