from __future__ import annotations

import pytest

from ming_drlms_gui.state import Session
from ming_drlms_gui.viewmodels.rooms_view_model import RoomsViewModel


class DummySock:
    def __init__(self) -> None:
        self.sent = []

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return "<DummySock>"


@pytest.fixture()
def session() -> Session:
    sess = Session()
    sess.authed = True
    sess.sock = DummySock()
    sess.subscribe_to_room(
        "dev",
        since_id=0,
        instance_id="instance-dev",
        presence_token="presence-self",
        display_token="IGNITED:presence-self",
    )
    return sess


def test_friend_flow_routes_through_view_model(
    monkeypatch: pytest.MonkeyPatch, session: Session
) -> None:
    view_model = RoomsViewModel(session)
    view_model.current_room_id = "dev"
    view_model.current_room_name = "dev"

    stranger = session.ensure_participant(
        "dev",
        "SILHOUETTE:presence-guest",
        presence_token="presence-guest",
    )
    stranger_alias = stranger.alias

    ignite_calls = []

    def fake_ignite_request(
        sock, room, instance, token
    ):  # pragma: no cover - patched path
        ignite_calls.append((room, instance, token))
        return True, "ignite-req", "OK|IGNITE|ignite-req"

    monkeypatch.setattr(
        "ming_drlms_gui.viewmodels.rooms_view_model.ignite_request",
        fake_ignite_request,
    )

    ok, req_id = view_model.request_ignite(stranger_alias)
    assert ok is True
    assert req_id == "ignite-req"
    assert ignite_calls == [("dev", "instance-dev", "presence-guest")]

    # server promotes the guest to ignited visibility with new token
    ignited_info = session.ensure_participant(
        "dev",
        "IGNITED:presence-guest",
        presence_token="presence-guest",
    )
    ignited_alias = ignited_info.alias

    befriend_calls = []

    def fake_befriend_request(
        sock, room, instance, token
    ):  # pragma: no cover - patched path
        befriend_calls.append((room, instance, token))
        return True, "friend-req", "OK|BEFRIEND|friend-req"

    monkeypatch.setattr(
        "ming_drlms_gui.viewmodels.rooms_view_model.befriend_request",
        fake_befriend_request,
    )

    ok, friend_req = view_model.request_befriend(ignited_alias)
    assert ok is True
    assert friend_req == "friend-req"
    assert befriend_calls == [("dev", "instance-dev", "presence-guest")]

    # server promotes visibility and sends established event
    friend_info = session.ensure_participant(
        "dev",
        "FRIEND:Sky_Buddy:presence-guest",
        presence_token="presence-guest",
    )
    assert friend_info.alias == "Sky Buddy"

    # remote user accepts the friend request and we receive the event
    view_model.on_befriend_established(
        {
            "room_name": "dev",
            "alias": "Sky Buddy",
            "display_token": "FRIEND:Sky_Buddy:presence-guest",
            "note_override": "First spark",
        }
    )

    assert session.is_friend_alias("Sky Buddy") is True
    assert session.friend_notes["Sky Buddy"] == "First spark"

    # note updates propagate to all participants
    view_model.on_note_updated(
        {
            "alias": "Sky Buddy",
            "note_override": "Shared memories",
        }
    )
    assert session.friend_notes["Sky Buddy"] == "Shared memories"

    # joining another room with the same friend should reuse the alias & note
    session.subscribe_to_room(
        "design",
        since_id=0,
        instance_id="instance-design",
    )
    friend_in_other_room = session.ensure_participant(
        "design",
        "FRIEND:Sky_Buddy:presence-guest",
        presence_token="presence-guest",
    )
    assert friend_in_other_room.alias == "Sky Buddy"
    assert friend_in_other_room.note_override == "Shared memories"
