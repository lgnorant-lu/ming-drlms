import socket
from datetime import datetime
from typing import cast

from ming_drlms_gui.components.room_content import RoomContent
from ming_drlms_gui.state import Session
from ming_drlms.core.types import RoomInfo


def _make_session(user: str = "tester") -> Session:
    sess = Session()
    sess.authed = True
    sess.sock = cast(socket.socket, object())
    sess.event_sock = None
    sess.user = user
    return sess


def _make_room(name: str = "general", owner: str = "owner") -> RoomInfo:
    return RoomInfo(
        name=name,
        owner=owner,
        policy=0,
        subscriber_count=5,
        last_event_id=0,
        created_at=int(datetime.now().timestamp()),
        updated_at=int(datetime.now().timestamp()),
    )


def test_load_history_appends_new_entries_without_animation(monkeypatch):
    sess = _make_session()
    room = _make_room()
    sess.available_rooms.append(room)

    content = RoomContent({}, sess)
    content.current_room_id = room.name
    content.current_room_name = room.name
    sess.set_current_room(room.name)

    history_payload = [
        {
            "event_id": 101,
            "user": "alice",
            "message": "hello",
            "timestamp": "2024-01-01T00:00:00Z",
        },
        {
            "event_id": 102,
            "user": "bob",
            "message": "world",
            "timestamp": "2024-01-01T00:01:00Z",
        },
    ]

    monkeypatch.setattr(
        "ming_drlms_gui.components.chat_panel.get_history",
        lambda sock, room_name, since_id=0, limit=50: history_payload,
    )

    appended = content._load_history()

    assert appended == 2
    assert len(content.messages) == 2
    assert {101, 102} <= sess.global_displayed_messages
    assert content.messages[0]["flash"] is False
    assert content.messages[1]["flash"] is False
    assert sess.get_room_max_event_id(room.name) == 102


def test_load_history_skips_displayed_duplicates(monkeypatch):
    sess = _make_session()
    room = _make_room()
    sess.available_rooms.append(room)
    sess.mark_message_displayed(200)

    content = RoomContent({}, sess)
    content.current_room_id = room.name
    content.current_room_name = room.name
    sess.set_current_room(room.name)

    history_payload = [
        {
            "event_id": 200,
            "user": "alice",
            "message": "duplicate",
            "timestamp": "2024-01-01T00:00:00Z",
        },
        {
            "event_id": 201,
            "user": "bob",
            "message": "fresh",
            "timestamp": "2024-01-01T00:01:00Z",
        },
    ]

    monkeypatch.setattr(
        "ming_drlms_gui.components.chat_panel.get_history",
        lambda sock, room_name, since_id=0, limit=50: history_payload,
    )

    appended = content._load_history()

    assert appended == 1
    assert len(content.messages) == 1
    assert content.messages[0]["event_id"] == 201
    assert content.messages[0]["flash"] is False
    assert 201 in sess.global_displayed_messages


def test_on_message_received_increments_unread_for_other_rooms():
    sess = _make_session()
    current_room = "room1"
    other_room = "room2"

    content = RoomContent({}, sess)
    content.current_room_id = current_room
    content.current_room_name = current_room
    sess.set_current_room(current_room)

    content._on_message_received(other_room, "alice", "hi", event_id=301)

    assert sess.get_unread(other_room) == 1
    assert 301 not in sess.global_displayed_messages
    assert sess.get_room_max_event_id(other_room) == 301
    assert "alice" in sess.get_room_users(other_room)
    assert len(content.messages) == 0

    content._on_message_received(current_room, "bob", "hey", event_id=302)

    assert sess.get_unread(current_room) == 0
    assert 302 in sess.global_displayed_messages
    assert len(content.messages) == 1
    assert content.messages[0]["event_id"] == 302
    assert content.messages[0]["flash"] is True
