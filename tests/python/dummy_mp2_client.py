from __future__ import annotations

import itertools
from typing import Iterable

from ming_drlms.core.e2ee_store import LocalKeyStore
from ming_drlms.core.mproto_v2_client import (
    E2EEPreKeyBundle,
    RoomEvent,
    RoomMember,
    SignalSenderKeyDistribution,
)


class DummyMP2Client:
    """Minimal in-memory MP2 client stub for E2EE unit tests."""

    def __init__(self, store_path) -> None:
        self._store_path = store_path
        self._events: list[RoomEvent] = []
        self._counter = itertools.count(1)
        self._members: dict[str, list[RoomMember]] = {}
        self._pending_sender_keys: dict[
            tuple[str, str], list[SignalSenderKeyDistribution]
        ] = {}

    # ------------------------------------------------------------------
    # Publish/subscribe -------------------------------------------------
    # ------------------------------------------------------------------
    def publish(
        self,
        user: str,
        room: str,
        payload: bytes,
        *,
        ephemeral: bool,
        encrypted_payload=None,
    ) -> None:
        if encrypted_payload is not None:
            pre_key_id = encrypted_payload.pre_key_id or None
            signed_id = encrypted_payload.signed_pre_key_id or None
            event_payload = bytes(encrypted_payload.ciphertext)
            payload_type = encrypted_payload.type
            sender_device = encrypted_payload.sender_device_id
            sender_reg = encrypted_payload.sender_registration_id
            group_id = encrypted_payload.group_id or None
            sender_iteration = encrypted_payload.sender_key_iteration or None
        else:
            pre_key_id = None
            signed_id = None
            event_payload = payload
            payload_type = None
            sender_device = None
            sender_reg = None
            group_id = None
            sender_iteration = None

        event = RoomEvent(
            room_name=room,
            event_id=next(self._counter),
            payload=event_payload,
            display_token="event",
            payload_type=payload_type,
            sender=user,
            sender_device_id=sender_device,
            sender_registration_id=sender_reg,
            pre_key_id=pre_key_id,
            signed_pre_key_id=signed_id,
            group_id=group_id,
            sender_key_iteration=sender_iteration,
        )
        self._events.append(event)

    def subscribe(
        self,
        user: str,
        room: str,
        *,
        since_id: int = 0,
        sender_key_callback=None,
    ):
        def _iter():
            if sender_key_callback is not None:
                pending = self._pending_sender_keys.pop((room, user), [])
                for distribution in pending:
                    sender_key_callback(distribution)
            for event in list(self._events):
                if event.event_id > since_id:
                    yield event

        return _iter()

    def get_room_members(self, username: str, room_name: str) -> "list[RoomMember]":
        return list(self._members.get(room_name, []))

    # ------------------------------------------------------------------
    # E2EE helpers ------------------------------------------------------
    # ------------------------------------------------------------------
    def e2ee_fetch_prekey_bundle(
        self, requester: str, target_user: str
    ) -> E2EEPreKeyBundle:
        store = LocalKeyStore(self._store_path)
        state = store.load_state(target_user)
        if state is None:
            return E2EEPreKeyBundle(
                code=404,
                message="no keys",
                identity_key=None,
                registration_id=0,
                device_id=0,
                pre_key_id=0,
                pre_key_public=None,
                signed_pre_key_id=0,
                signed_pre_key_public=None,
                signed_pre_key_signature=None,
            )

        pre_key_item = next(iter(state.pre_keys.items()))
        pre_key_id, pre_key_pair = pre_key_item
        signed_pre_key = state.signed_pre_key
        if signed_pre_key is None:
            raise AssertionError("signed pre-key missing in test setup")

        return E2EEPreKeyBundle(
            code=0,
            message="ok",
            identity_key=state.identity_key.public_key,
            registration_id=state.registration_id,
            device_id=state.device_id,
            pre_key_id=pre_key_id,
            pre_key_public=pre_key_pair.public_key,
            signed_pre_key_id=signed_pre_key.id,
            signed_pre_key_public=signed_pre_key.key.public_key,
            signed_pre_key_signature=signed_pre_key.signature,
        )

    def e2ee_sender_key_push(
        self,
        username: str,
        target_user: str,
        distribution: SignalSenderKeyDistribution,
    ) -> tuple[int, str]:
        key = (distribution.room_name, target_user)
        self._pending_sender_keys.setdefault(key, []).append(distribution)
        return 0, "ok"

    # ------------------------------------------------------------------
    # Test helpers ------------------------------------------------------
    # ------------------------------------------------------------------
    def set_room_members(self, room: str, members: Iterable[RoomMember]) -> None:
        self._members[room] = list(members)
