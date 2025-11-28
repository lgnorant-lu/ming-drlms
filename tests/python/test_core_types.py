from __future__ import annotations

import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).parents[3] / "src"))

from ming_drlms.core.types import RoomInfo


def test_room_info_defaults() -> None:
    room = RoomInfo("room-1")
    assert room.name == "room-1"
    assert room.subscriber_count == 0
    assert room.storage_policy == 0
    assert room.max_capacity == 0
    assert room.instance_count == 0
    assert room.last_updated == 0
    assert room.owner == ""
    assert room.policy == 0
    assert room.last_event_id == 0
    assert room.created_at == 0
    assert room.updated_at == 0


def test_room_info_custom_values() -> None:
    room = RoomInfo(
        "room-x",
        subscriber_count=10,
        storage_policy=2,
        max_capacity=100,
        instance_count=3,
        last_updated=123456,
        owner="alice",
        policy=7,
        last_event_id=42,
        created_at=111,
        updated_at=222,
    )

    assert room.name == "room-x"
    assert room.subscriber_count == 10
    assert room.storage_policy == 2
    assert room.max_capacity == 100
    assert room.instance_count == 3
    assert room.last_updated == 123456
    assert room.owner == "alice"
    assert room.policy == 7
    assert room.last_event_id == 42
    assert room.created_at == 111
    assert room.updated_at == 222
