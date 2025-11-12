from pathlib import Path

import pytest

from ming_drlms.core.e2ee_store import LocalKeyStore
from ming_drlms.core.e2ee_runtime import E2EEngine
from ming_drlms.core.mproto_v2_client import E2EEPreKeyBundle, RoomEvent, SignalPreKey
from ming_drlms.core.pysignal import (
    GeneratedKeys,
    SignalBridgeError,
    create_signal_context,
    generate_device_keys,
)


class _FakeMP2Client:
    def __init__(self, bundles: dict[str, E2EEPreKeyBundle]):
        self._bundles = bundles

    def e2ee_fetch_prekey_bundle(
        self, username: str, target_user: str
    ) -> E2EEPreKeyBundle:
        return self._bundles[target_user]


def _bundle_from_generated(name: str, keys: GeneratedKeys) -> E2EEPreKeyBundle:
    first_pre_key: SignalPreKey = keys.pre_keys[0]
    return E2EEPreKeyBundle(
        code=0,
        message="ok",
        identity_key=keys.identity.public_key,
        registration_id=keys.registration_id,
        device_id=keys.device_id,
        pre_key_id=first_pre_key.id,
        pre_key_public=first_pre_key.key.public_key,
        signed_pre_key_id=keys.signed_pre_key.id,
        signed_pre_key_public=keys.signed_pre_key.key.public_key,
        signed_pre_key_signature=keys.signed_pre_key.signature,
    )


def test_e2ee_roundtrip(tmp_path: Path) -> None:
    try:
        ctx = create_signal_context()
    except SignalBridgeError as exc:
        pytest.skip(f"signal CFFI 构建失败: {exc}")
    try:
        alice_keys = generate_device_keys(ctx, pre_key_count=4, signed_pre_key_id=11)
        bob_keys = generate_device_keys(ctx, pre_key_count=4, signed_pre_key_id=21)

        store_path = tmp_path / "keys.json"
        key_store = LocalKeyStore(store_path)
        key_store.store_keys(
            "alice",
            registration_id=alice_keys.registration_id,
            device_id=alice_keys.device_id,
            identity=alice_keys.identity,
            signed_pre_key=alice_keys.signed_pre_key,
            pre_keys=alice_keys.pre_keys,
        )
        key_store.store_keys(
            "bob",
            registration_id=bob_keys.registration_id,
            device_id=bob_keys.device_id,
            identity=bob_keys.identity,
            signed_pre_key=bob_keys.signed_pre_key,
            pre_keys=bob_keys.pre_keys,
        )

        bundles = {
            "alice": _bundle_from_generated("alice", alice_keys),
            "bob": _bundle_from_generated("bob", bob_keys),
        }
        fake_client = _FakeMP2Client(bundles)

        engine_alice = E2EEngine(
            username="alice", key_store=key_store, mp2_client=fake_client
        )
        engine_bob = E2EEngine(
            username="bob", key_store=key_store, mp2_client=fake_client
        )
        try:
            plaintext = b"hello bob"
            payload = engine_alice.encrypt("bob", plaintext)
            event_for_bob = RoomEvent(
                room_name="chat",
                event_id=1,
                payload=bytes(payload.ciphertext),
                display_token="token",
                payload_type=payload.type,
                sender="alice",
                sender_device_id=alice_keys.device_id,
                sender_registration_id=alice_keys.registration_id,
                pre_key_id=payload.pre_key_id if payload.pre_key_id else None,
                signed_pre_key_id=(
                    payload.signed_pre_key_id if payload.signed_pre_key_id else None
                ),
            )
            decrypted = engine_bob.decrypt(event_for_bob)
            assert decrypted.plaintext == plaintext

            bob_state = key_store.load_state("bob")
            assert bob_state is not None
            assert (
                decrypted.info.pre_key_id is None
                or decrypted.info.pre_key_id not in bob_state.pre_keys
            )

            reply = b"hi alice"
            payload_back = engine_bob.encrypt("alice", reply)
            event_for_alice = RoomEvent(
                room_name="chat",
                event_id=2,
                payload=bytes(payload_back.ciphertext),
                display_token="token2",
                payload_type=payload_back.type,
                sender="bob",
                sender_device_id=bob_keys.device_id,
                sender_registration_id=bob_keys.registration_id,
                pre_key_id=payload_back.pre_key_id if payload_back.pre_key_id else None,
                signed_pre_key_id=(
                    payload_back.signed_pre_key_id
                    if payload_back.signed_pre_key_id
                    else None
                ),
            )
            decrypted_back = engine_alice.decrypt(event_for_alice)
            assert decrypted_back.plaintext == reply

            alice_state = key_store.load_state("alice")
            assert alice_state is not None
            assert (
                decrypted_back.info.pre_key_id is None
                or decrypted_back.info.pre_key_id not in alice_state.pre_keys
            )
        finally:
            engine_alice.close()
            engine_bob.close()
    finally:
        ctx.close()
