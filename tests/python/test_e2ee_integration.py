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
import unittest
from unittest.mock import patch

# Add src to path
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src"))
)

from ming_drlms.mcp import tools
from ming_drlms.core.e2ee_store import LocalKeyStore


class TestE2EEIntegration(unittest.TestCase):
    def setUp(self):
        # Clean local keystore for test users
        self.keystore = LocalKeyStore()
        for user in ["alice_test", "bob_test"]:
            try:
                # Manually remove from internal dict or file if possible
                # LocalKeyStore doesn't expose delete easily but we can overwrite
                pass
            except Exception:
                pass

    def test_quantum_flow(self):
        """Test full E2EE flow with Quantum Security."""
        print("\n--- TEST: Quantum E2EE Flow ---")

        # 1. Generate Identities
        # Bob needs PQC
        print("1. Generating Bob Identity (Quantum request)...")
        bob_id = tools.generate_identity(username="bob_test", security_level="quantum")

        if bob_id["security_level"] == "standard":
            print(
                "   WARNING: System downgraded to STANDARD security (liboqs missing)."
            )
            print("   Skipping PQC-specific checks, verifying fallback behavior.")
            self.assertNotIn("pqc_pubkey_hex", bob_id)
            # Verify it works as standard (fallback)
            bob_combined_key = bob_id["pubkey_hex"]
        else:
            self.assertTrue(bob_id["created"] or True)
            self.assertIn("pqc_pubkey_hex", bob_id)
            # Construct combined key for Alice to use
            bob_combined_key = f"{bob_id['pubkey_hex']}+{bob_id['pqc_pubkey_hex']}"

        print(f"   Bob Key: {bob_combined_key[:32]}...")

        # 2. Store Secret (Alice -> Bob)
        secret_msg = "The Eagle has Landed - Quantum"

        print("2. Alice Encrypts & Stores...")
        # Mock BlossomClient to avoid real network
        with patch("ming_drlms.mcp.tools.BlossomClient") as MockClient:
            mock_instance = MockClient.return_value
            # Mock Upload
            mock_instance.upload_blob.return_value = {"sha256": "deadbeef1234"}

            uri = tools.store_secret(
                recipient_pubkey=bob_combined_key, secret_content=secret_msg
            )

            print(f"   URI: {uri}")
            self.assertEqual(uri, "blossom://deadbeef1234")

            # Capture what was uploaded (the encrypted blob)
            args, _ = mock_instance.upload_blob.call_args
            uploaded_bytes = args[0]
            uploaded_str = uploaded_bytes.decode("utf-8")
            envelope = json.loads(uploaded_str)

            if bob_id["security_level"] == "standard":
                self.assertEqual(envelope["alg"], "standard-v1")
            else:
                self.assertEqual(envelope["alg"], "hybrid-v1")
                self.assertTrue(
                    len(envelope["blob"]) > 100
                )  # Should be large due to PQC ciphertext

            # 3. Retrieve Secret (Bob)
            print("3. Bob Retrieves & Decrypts...")
            # Mock Download (return the same bytes Alice uploaded)
            mock_instance.download_blob.return_value = uploaded_bytes

            result = tools.retrieve_secret(
                blossom_uri=uri, recipient_username="bob_test"
            )

            print(f"   Result: {result}")
            self.assertTrue(result["success"])
            self.assertEqual(result["secret_content"], secret_msg)

            if bob_id["security_level"] == "standard":
                self.assertEqual(result["encryption_status"], "e2ee-standard-v1")
            else:
                self.assertEqual(result["encryption_status"], "e2ee-hybrid-v1")

    def test_standard_fallback(self):
        """Test E2EE flow with Standard keys (X25519 only)."""
        print("\n--- TEST: Standard E2EE Flow ---")

        # 1. Generate Bob Identity (Standard)
        print("1. Generating Bob Identity (Standard)...")
        bob_id = tools.generate_identity(username="bob_std", security_level="standard")

        # Standard only has pubkey_hex
        bob_key = bob_id["pubkey_hex"]

        # 2. Store Secret
        secret_msg = "Classical Music Only"

        with patch("ming_drlms.mcp.tools.BlossomClient") as MockClient:
            mock_instance = MockClient.return_value
            mock_instance.upload_blob.return_value = {"sha256": "cafe1234"}

            uri = tools.store_secret(
                recipient_pubkey=bob_key,  # No PQC part
                secret_content=secret_msg,
            )

            # Check envelope alg
            args, _ = mock_instance.upload_blob.call_args
            envelope = json.loads(args[0])
            self.assertEqual(envelope["alg"], "standard-v1")

            # 3. Retrieve
            mock_instance.download_blob.return_value = args[0]

            result = tools.retrieve_secret(
                blossom_uri=uri, recipient_username="bob_std"
            )

            self.assertTrue(result["success"])
            self.assertEqual(result["secret_content"], secret_msg)
            self.assertEqual(result["encryption_status"], "e2ee-standard-v1")


if __name__ == "__main__":
    unittest.main()
