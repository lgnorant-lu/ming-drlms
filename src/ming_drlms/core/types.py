from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RoomInfo:
    """共享予 CLI 与 GUI 的 room metadata."""

    name: str
    subscriber_count: int = 0
    storage_policy: int = 0
    max_capacity: int = 0
    instance_count: int = 0
    last_updated: int = 0
    owner: str = ""
    policy: int = 0
    last_event_id: int = 0
    created_at: int = 0
    updated_at: int = 0


__all__ = ["RoomInfo"]
