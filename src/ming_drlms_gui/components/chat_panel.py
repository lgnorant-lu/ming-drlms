from __future__ import annotations

from typing import Any, Dict, List


def get_history(
    sock: Any, room_name: str, since_id: int = 0, limit: int = 50
) -> List[Dict[str, Any]]:
    """Fetch room history (MP2-only placeholder).

    GUI adapter pending MP2 mapping; return empty history by default.
    """
    if not sock or not room_name:
        return []
    return []
