from __future__ import annotations

from ming_drlms_gui.components.room_list import RoomList
from ming_drlms_gui.state import Session
from ming_drlms.core.types import RoomInfo


def make_room(
    name: str,
    owner: str = "alice",
    policy: int = 0,
    subscribers: int = 0,
    last_event: int = 0,
    created: int = 0,
    updated: int = 0,
) -> RoomInfo:
    return RoomInfo(
        name=name,
        owner=owner,
        policy=policy,
        subscriber_count=subscribers,
        last_event_id=last_event,
        created_at=created,
        updated_at=updated,
    )


def test_fuzzy_search_ranks_exact_and_prefix_matches():
    sess = Session()
    room_list = RoomList({}, sess)
    room_list.rooms = [
        make_room("alpha"),
        make_room("ops"),
        make_room("devops"),
    ]

    room_list.sort_mode = "alphabetical"
    matches = room_list._apply_filters_and_sort("ops")

    assert [room.name for room in matches] == ["ops", "devops"]


def test_sort_by_unread_descending():
    sess = Session()
    sess.increment_unread("dev", 2)
    sess.increment_unread("ops", 1)

    room_list = RoomList({}, sess)
    room_list.rooms = [
        make_room("general", subscribers=5, last_event=3),
        make_room("ops", subscribers=2, last_event=8),
        make_room("dev", subscribers=4, last_event=5),
    ]

    room_list.sort_mode = "unread"
    ordered = room_list._apply_filters_and_sort()

    assert [room.name for room in ordered] == ["dev", "ops", "general"]


def test_fuzzy_search_fallback_returns_top_candidates():
    sess = Session()
    room_list = RoomList({}, sess)
    room_list.rooms = [
        make_room("zulu"),
        make_room("beta"),
        make_room("alpha"),
    ]

    room_list.sort_mode = "smart"
    results = room_list._apply_filters_and_sort("zzz")

    assert len(results) == len(room_list.rooms)
    assert {room.name for room in results} == {"alpha", "beta", "zulu"}
    assert results[0].name == "zulu"
