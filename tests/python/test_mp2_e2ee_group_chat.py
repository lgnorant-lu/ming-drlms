from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from ming_drlms.cli.services.room_service import RoomService
from ming_drlms.core.e2ee_store import LocalKeyStore
from ming_drlms.core.mproto_v2_client import RoomMember
from ming_drlms.core.pysignal import create_signal_context, generate_device_keys

from .dummy_mp2_client import DummyMP2Client


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


def test_room_service_group_roundtrip(tmp_path: Path) -> None:
    keystore_path = tmp_path / "keys.json"
    store = LocalKeyStore(keystore_path)
    _generate_and_store_keys(store, "alice", signed_id=11)
    _generate_and_store_keys(store, "bob", signed_id=21)
    _generate_and_store_keys(store, "carol", signed_id=31)

    dummy_client = DummyMP2Client(keystore_path)
    dummy_client.set_room_members(
        "chat",
        [
            RoomMember(user_id="alice", device_id=1, timestamp="t1"),
            RoomMember(user_id="bob", device_id=1, timestamp="t1"),
            RoomMember(user_id="carol", device_id=1, timestamp="t1"),
        ],
    )

    def client_factory(*args, **kwargs):
        @contextmanager
        def _ctx():
            yield dummy_client

        return _ctx()

    service = RoomService(client_factory=client_factory)

    message = b"group secret"
    result = service.publish(
        host="127.0.0.1",
        port=443,
        user="alice",
        room="chat",
        payload=message,
        ephemeral=False,
        token_store=None,
        timeout=5.0,
        e2ee_store=keystore_path,
    )
    assert result.bytes_sent == len(message)

    bob_iter = service.subscribe(
        host="127.0.0.1",
        port=443,
        user="bob",
        room="chat",
        since_id=0,
        token_store=None,
        timeout=5.0,
        e2ee_store=keystore_path,
    )
    carol_iter = service.subscribe(
        host="127.0.0.1",
        port=443,
        user="carol",
        room="chat",
        since_id=0,
        token_store=None,
        timeout=5.0,
        e2ee_store=keystore_path,
    )

    bob_event = next(bob_iter)
    carol_event = next(carol_iter)

    for event in (bob_event, carol_event):
        assert event.payload == message
        assert event.sender == "alice"
        assert event.group_id == "chat"
        assert event.sender_key_iteration is not None

    bob_iter.close()
    carol_iter.close()
