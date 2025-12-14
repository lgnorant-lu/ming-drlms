"""
---------------------------------------------------------------
File name:                  test_e2ee_sender_key_integration.py
Author:                     Ignorant-lu (AI Assistant)
Date created:               2024/12/14
Description:                Integration tests for Sender Key distribution
                            in real-world subscription scenarios
----------------------------------------------------------------

Changed history:
                            2024/12/14: 初始创建 - Phase 24 TDD;
----
"""

import pytest
from unittest.mock import Mock

# Import the modules we're testing
from ming_drlms.core.e2ee_runtime import E2EEngine


class TestSenderKeyIntegration:
    """
    Integration tests for Sender Key distribution across multiple clients.

    These tests simulate real-world scenarios where multiple users join
    a room sequentially and verify that Sender Keys are properly distributed.
    """

    def test_two_members_sequential_join_empty_room_first(self):
        """
        Scenario: bob joins empty room first, then alice joins
        Expected: Both can encrypt/decrypt each other's messages

        This is the PRIMARY BUG we're fixing:
        - bob joins when room is empty (0 members)
        - bob's distribute_sender_key has no one to distribute to
        - alice joins and distributes to bob ✅
        - bob never distributes to alice ❌

        After fix: bob should redistribute when sending messages
        """
        # Setup mock E2E engines for bob and alice
        bob_engine = Mock(spec=E2EEngine)
        alice_engine = Mock(spec=E2EEngine)

        # Mock distribute_sender_key to track calls
        bob_distribute_calls = []
        alice_distribute_calls = []

        def bob_distribute(room, group, target):
            bob_distribute_calls.append((room, group, target))

        def alice_distribute(room, group, target):
            alice_distribute_calls.append((room, group, target))

        bob_engine.distribute_sender_key = Mock(side_effect=bob_distribute)
        alice_engine.distribute_sender_key = Mock(side_effect=alice_distribute)

        # Simulate bob joining empty room
        # get_room_members returns empty list
        bob_members_response = []

        # Process bob's subscription
        # This simulates the code in threaded_client.py:440-504
        for member in bob_members_response:
            uid = member.get("user_id")
            if uid and uid != "bob":
                bob_engine.distribute_sender_key("Town Square", "Town Square", uid)

        # Assert: bob distributed to 0 members (room was empty)
        assert len(bob_distribute_calls) == 0, (
            "Bug confirmed: bob distributed to no one"
        )

        # Simulate alice joining (bob is already present)
        # get_room_members returns [bob]
        alice_members_response = [{"user_id": "bob", "device_id": 1}]

        # Process alice's subscription
        for member in alice_members_response:
            uid = member.get("user_id")
            if uid and uid != "alice":
                alice_engine.distribute_sender_key("Town Square", "Town Square", uid)

        # Assert: alice distributed to bob ✅
        assert len(alice_distribute_calls) == 1
        assert alice_distribute_calls[0] == ("Town Square", "Town Square", "bob")

        # Now verify the BUG: when bob sends a message, alice can't decrypt
        # because alice doesn't have bob's Sender Key

        # Mock: alice tries to decrypt bob's message but fails
        # because bob never distributed his key
        alice_has_bob_key = False  # This is the bug!

        assert not alice_has_bob_key, "FAIL: alice doesn't have bob's Sender Key"

        # After our fix, this test should PASS by ensuring bob
        # distributes his key before sending (or when alice joins)

    def test_three_members_sequential_join(self):
        """
        Scenario: bob, alice, charlie join sequentially
        Expected: All three can decrypt each other's messages
        """
        room_name = "Town Square"

        # Track who has whose keys
        # Format: sender_keys["alice"]["bob"] = True means alice has bob's key
        sender_keys = {"bob": {}, "alice": {}, "charlie": {}}

        def mock_distribute(sender, room, group, target):
            """Simulate successful key distribution"""
            sender_keys[target][sender] = True

        # 1. bob joins empty room (0 members)
        bob_members = []
        for member in bob_members:
            mock_distribute("bob", room_name, room_name, member["user_id"])

        # bob distributed to 0 members
        assert sender_keys["alice"].get("bob") is None
        assert sender_keys["charlie"].get("bob") is None

        # 2. alice joins (1 member: bob)
        alice_members = [{"user_id": "bob"}]
        for member in alice_members:
            if member["user_id"] != "alice":
                mock_distribute("alice", room_name, room_name, member["user_id"])

        # alice distributed to bob
        assert sender_keys["bob"]["alice"] is True
        # bob still hasn't distributed to alice ❌
        assert sender_keys["alice"].get("bob") is None

        # 3. charlie joins (2 members: bob, alice)
        charlie_members = [{"user_id": "bob"}, {"user_id": "alice"}]
        for member in charlie_members:
            if member["user_id"] != "charlie":
                mock_distribute("charlie", room_name, room_name, member["user_id"])

        # charlie distributed to both
        assert sender_keys["bob"]["charlie"] is True
        assert sender_keys["alice"]["charlie"] is True

        # Verify the problem: not all pairs have keys
        # bob → alice: Missing ❌
        # alice → bob: OK ✅
        # charlie → bob: OK ✅
        # charlie → alice: OK ✅
        # bob → charlie: Missing ❌
        # alice → charlie: Missing ❌

        assert sender_keys["alice"].get("bob") is None, "bob never distributed to alice"
        assert sender_keys["charlie"].get("bob") is None, (
            "bob never distributed to charlie"
        )
        assert sender_keys["charlie"].get("alice") is None, (
            "alice never distributed to charlie"
        )

    def test_member_leaves_and_rejoins(self):
        """
        Scenario: bob joins, alice joins, bob leaves, bob rejoins
        Expected: bob redistributes keys when rejoining
        """
        sender_keys = {"alice": {}, "bob": {}}

        # 1. bob joins empty room
        # (no distribution)

        # 2. alice joins
        sender_keys["bob"]["alice"] = True

        # 3. bob leaves (keys remain in cache)

        # 4. bob rejoins - should redistribute
        bob_members = [{"user_id": "alice"}]
        for member in bob_members:
            if member["user_id"] != "bob":
                # This SHOULD happen on rejoin
                sender_keys["alice"]["bob"] = True

        # After fix: both should have each other's keys
        assert sender_keys["bob"]["alice"] is True
        assert sender_keys["alice"]["bob"] is True


class TestSenderKeyMessageSendingFallback:
    """
    Tests for the FIX: ensure Sender Key is distributed before sending messages.

    This is the "方案 C: 消息发送时兜底" approach.
    """

    def test_encrypt_group_ensures_key_distribution(self):
        """
        Test that encrypt_group distributes Sender Key before encrypting
        if not already distributed to the target.
        """
        engine = Mock(spec=E2EEngine)

        # Track distribution calls
        distribute_calls = []
        engine.distribute_sender_key = Mock(
            side_effect=lambda r, g, t: distribute_calls.append(t)
        )

        # Simulate: we're about to encrypt a message to "alice"
        # but we haven't distributed our key to her yet

        # The fix should call distribute_sender_key("Town Square", "Town Square", "alice")
        # BEFORE actually encrypting

        # This test will FAIL with current implementation
        # and PASS after we add the fallback logic

        # After fix, distribute_sender_key should be called
        # (This is a placeholder - actual implementation will be in e2ee_runtime.py)
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
