from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RoomInfo:
    """共享予 CLI 与 GUI 的 room metadate 的 layers."""

    name: str
    owner: str
    policy: int
    subscriber_count: int
    last_event_id: int
    created_at: int
    updated_at: int = 0


__all__ = ["RoomInfo"]
