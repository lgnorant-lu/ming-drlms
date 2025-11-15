import itertools
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from ming_drlms.core.e2ee_store import LocalKeyStore
from ming_drlms.core.pysignal import create_signal_context, generate_device_keys
from ming_drlms.core.mproto_v2_client import (
    E2EEPreKeyBundle,
    RoomEvent,
)
from ming_drlms.cli.services.room_service import RoomService


class _DummyMP2Client:
    def __init__(self, store_path: Path) -> None:
        self._store_path = store_path
        self._events: list[RoomEvent] = []
        self._counter = itertools.count(1)

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
        else:
            pre_key_id = None
            signed_id = None
            event_payload = payload
            payload_type = None
            sender_device = None
            sender_reg = None

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
        )
        self._events.append(event)

    def subscribe(self, user: str, room: str, *, since_id: int = 0):
        for event in list(self._events):
            if event.event_id > since_id:
                yield event

    # MP2Client API shim -------------------------------------------------
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


def _generate_and_store_keys(
    store: LocalKeyStore, username: str, *, signed_id: int
) -> None:
    ctx = create_signal_context()
    try:
        generated = generate_device_keys(
            ctx,
            pre_key_count=5,
            signed_pre_key_id=signed_id,
        )
    finally:
        ctx.close()

    store.store_keys(
        username,
        registration_id=generated.registration_id,
        device_id=generated.device_id,
        identity=generated.identity,
        signed_pre_key=generated.signed_pre_key,
        pre_keys=generated.pre_keys,
    )


@pytest.mark.skipif(
    os.getenv("CI") == "true",
    reason="E2E encryption tests require OpenSSL DLLs which may not be available in CI",
)
def test_room_service_e2ee_roundtrip(tmp_path: Path) -> None:
    keystore_path = tmp_path / "keys.json"
    store = LocalKeyStore(keystore_path)
    _generate_and_store_keys(store, "alice", signed_id=11)
    _generate_and_store_keys(store, "bob", signed_id=21)

    dummy_client = _DummyMP2Client(keystore_path)

    def client_factory(*args, **kwargs):
        @contextmanager
        def _ctx():
            yield dummy_client

        return _ctx()

    service = RoomService(client_factory=client_factory)

    message = b"Hello E2EE"
    result = service.publish(
        host="127.0.0.1",
        port=443,
        user="alice",
        room="chat",
        payload=message,
        ephemeral=False,
        token_store=None,
        timeout=5.0,
        e2ee_peer="bob",
        e2ee_store=keystore_path,
    )
    assert result.bytes_sent == len(message)

    iterator = service.subscribe(
        host="127.0.0.1",
        port=443,
        user="bob",
        room="chat",
        since_id=0,
        token_store=None,
        timeout=5.0,
        e2ee_peer="alice",
        e2ee_store=keystore_path,
    )

    event = next(iterator)
    assert event.payload == message
    assert event.sender == "alice"
    iterator.close()
