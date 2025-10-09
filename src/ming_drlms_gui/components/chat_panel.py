from __future__ import annotations

from typing import Any, Dict, List

from ming_drlms.core.room_protocol import get_history as _core_get_history


def get_history(
    sock: Any, room_name: str, since_id: int = 0, limit: int = 50
) -> List[Dict[str, Any]]:
    """Fetch room history via the shared core protocol."""

    if not sock or not room_name:
        return []
    return _core_get_history(sock, room_name, since_id=since_id, limit=limit)
