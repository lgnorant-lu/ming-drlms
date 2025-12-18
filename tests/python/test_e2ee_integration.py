"""Test Phase 28.1 E2EE Integration.

Verifies the Agent-to-Agent flow:
1. Generate Identities (Alice & Bob)
2. Alice encrypts for Bob (Hybrid X25519+ML-KEM)
3. Upload to (Mock) Blossom
4. Bob downloads from (Mock) Blossom
5. Bob decrypts
"""

import sys
import os
import json
import pytest
from unittest.mock import patch

# Add src to path
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from ming_drlms.mcp import tools
from ming_drlms.core.e2ee_store import LocalKeyStore
from ming_drlms.core.identity_manager import IdentityManager
from ming_drlms.core.nostr_derivation import generate_mnemonic


@pytest.fixture
def clean_keystore(tmp_path):
    """Fixture to provide a clean LocalKeyStore in a temp directory."""
    # Create temp keystore file
    ks_path = tmp_path / "test_keystore.json"
    return LocalKeyStore(str(ks_path))


@pytest.fixture
def mock_blossom_client():
    """Mock BlossomClient interaction."""
    with patch("ming_drlms.mcp.tools.BlossomClient") as MockClient:
        mock_instance = MockClient.return_value
        # Default mock behavior
        mock_instance.upload_blob.return_value = {"sha256": "deadbeef1234"}
        yield mock_instance


def test_nostr_lifecycle(clean_keystore):
    """Test complete Nostr key lifecycle (Phase 28.2).

    Verifies:
    1. Creation from mnemonic
    2. Persistence in LocalKeyStore
    3. Signer retrieval via IdentityManager
    4. Valid Schnorr signature generation
    """
    print("\n--- TEST: Nostr Key Lifecycle ---")

    # 1. Generate & Create
    username = "nostr_integ_test"
    mnemonic = generate_mnemonic()
    print(f"1. Creating identity '{username}'...")

    # Use clean keystore
    identity = IdentityManager.from_mnemonic(
        mnemonic, username, keystore=clean_keystore
    )

    # 2. Verify Persistence
    print("2. Verifying persistence...")
    state = clean_keystore.load_state(username)

    assert state.nostr_private_key is not None, "Nostr private key not persisted"
    assert state.nostr_public_key is not None, "Nostr public key not persisted"
    assert len(state.nostr_private_key) == 32

    # 3. Get Signer
    print("3. Retrieving NostrSigner...")
    signer = identity.get_nostr_signer()
    pubkey = signer.get_pubkey_hex()

    assert len(pubkey) == 64
    assert pubkey == state.nostr_public_key.hex()

    # 4. Sign Event
    print("4. Signing Event (BIP-340)...")
    event = {
        "pubkey": pubkey,
        "created_at": 1700000000,
        "kind": 1,
        "tags": [],
        "content": "Lifecycle Integration Test",
    }
    sig = signer.sign_event(event)

    assert len(sig) == 128
    print(f"   Signature: {sig[:16]}...")
    print("✅ Nostr Lifecycle OK")


def test_quantum_flow(mock_blossom_client):
    """Test full E2EE flow with Quantum Security."""
    print("\n--- TEST: Quantum E2EE Flow ---")

    # 1. Generate Identities
    # Bob needs PQC
    print("1. Generating Bob Identity (Quantum request)...")
    bob_id = tools.generate_identity(username="bob_test", security_level="quantum")

    if bob_id["security_level"] == "standard":
        print("   WARNING: System downgraded to STANDARD security (liboqs missing).")
        print("   Skipping PQC-specific checks, verifying fallback behavior.")
        assert "pqc_pubkey_hex" not in bob_id
        # Verify it works as standard (fallback)
        bob_combined_key = bob_id["pubkey_hex"]
    else:
        assert bob_id.get("created", True)
        assert "pqc_pubkey_hex" in bob_id
        # Construct combined key for Alice to use
        bob_combined_key = f"{bob_id['pubkey_hex']}+{bob_id['pqc_pubkey_hex']}"

    print(f"   Bob Key: {bob_combined_key[:32]}...")

    # 2. Store Secret (Alice -> Bob)
    secret_msg = "The Eagle has Landed - Quantum"

    print("2. Alice Encrypts & Stores...")

    # Setup mock return for this specific flow if needed

    uri = tools.store_secret(
        recipient_pubkey=bob_combined_key, secret_content=secret_msg
    )

    print(f"   URI: {uri}")
    assert uri == "blossom://deadbeef1234"

    # Capture what was uploaded (the encrypted blob)
    args, _ = mock_blossom_client.upload_blob.call_args
    uploaded_bytes = args[0]
    uploaded_str = uploaded_bytes.decode("utf-8")
    envelope = json.loads(uploaded_str)

    if bob_id["security_level"] == "standard":
        assert envelope["alg"] == "standard-v1"
    else:
        assert envelope["alg"] == "hybrid-v1"
        assert len(envelope["blob"]) > 100  # Should be large due to PQC ciphertext

    # 3. Retrieve Secret (Bob)
    print("3. Bob Retrieves & Decrypts...")
    # Mock Download (return the same bytes Alice uploaded)
    mock_blossom_client.download_blob.return_value = uploaded_bytes

    result = tools.retrieve_secret(blossom_uri=uri, recipient_username="bob_test")

    print(f"   Result: {result}")
    assert result["success"]
    assert result["secret_content"] == secret_msg

    if bob_id["security_level"] == "standard":
        assert result["encryption_status"] == "e2ee-standard-v1"
    else:
        assert result["encryption_status"] == "e2ee-hybrid-v1"


def test_standard_fallback(mock_blossom_client):
    """Test E2EE flow with Standard keys (X25519 only)."""
    print("\n--- TEST: Standard E2EE Flow ---")

    # 1. Generate Bob Identity (Standard)
    print("1. Generating Bob Identity (Standard)...")
    bob_id = tools.generate_identity(username="bob_std", security_level="standard")

    # Standard only has pubkey_hex
    bob_key = bob_id["pubkey_hex"]

    # 2. Store Secret
    secret_msg = "Classical Music Only"

    # Ensure mock returns consistent SHA
    mock_blossom_client.upload_blob.return_value = {"sha256": "cafe1234"}

    uri = tools.store_secret(
        recipient_pubkey=bob_key,  # No PQC part
        secret_content=secret_msg,
    )

    # Check envelope alg
    args, _ = mock_blossom_client.upload_blob.call_args
    envelope = json.loads(args[0])
    assert envelope["alg"] == "standard-v1"

    # 3. Retrieve
    mock_blossom_client.download_blob.return_value = args[0]

    result = tools.retrieve_secret(blossom_uri=uri, recipient_username="bob_std")

    assert result["success"]
    assert result["secret_content"] == secret_msg
    assert result["encryption_status"] == "e2ee-standard-v1"
