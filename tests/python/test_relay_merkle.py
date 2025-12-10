"""Phase 16B Unit Tests: Merkle Tree Module."""

from __future__ import annotations


from ming_drlms.relay.merkle import (
    MerkleTree,
    MerkleForest,
)


class TestMerkleTree:
    """Tests for MerkleTree."""

    def test_empty_tree(self):
        """Empty tree has zero root."""
        tree = MerkleTree("room1")
        assert tree.size == 0
        assert tree.root == b"\x00" * 32

    def test_single_event(self):
        """Single event tree has non-zero root."""
        tree = MerkleTree("room1")
        tree.add_event("event1")

        assert tree.size == 1
        assert tree.root != b"\x00" * 32
        assert len(tree.root) == 32

    def test_add_events_bulk(self):
        """Bulk add events."""
        tree = MerkleTree("room1")
        tree.add_events(["e1", "e2", "e3"])
        assert tree.size == 3

    def test_add_duplicate_ignored(self):
        """Adding duplicate event is ignored."""
        tree = MerkleTree("room1")
        tree.add_event("event1")
        tree.add_event("event1")
        assert tree.size == 1

    def test_contains(self):
        """contains checks event presence."""
        tree = MerkleTree("room1")
        tree.add_event("event1")

        assert tree.contains("event1") is True
        assert tree.contains("event2") is False

    def test_get_event_ids(self):
        """get_event_ids returns all events in order."""
        tree = MerkleTree("room1")
        tree.add_events(["e1", "e2", "e3"])

        ids = tree.get_event_ids()
        assert ids == ["e1", "e2", "e3"]

    def test_root_changes_with_events(self):
        """Root changes as events are added."""
        tree = MerkleTree("room1")

        tree.add_event("e1")
        root1 = tree.root

        tree.add_event("e2")
        root2 = tree.root

        assert root1 != root2

    def test_deterministic_root(self):
        """Same events produce same root."""
        tree1 = MerkleTree("room1")
        tree1.add_events(["e1", "e2", "e3"])

        tree2 = MerkleTree("room2")
        tree2.add_events(["e1", "e2", "e3"])

        assert tree1.root == tree2.root

    def test_order_matters(self):
        """Event order affects root (insertion order)."""
        tree1 = MerkleTree("room1")
        tree1.add_events(["e1", "e2", "e3"])

        tree2 = MerkleTree("room2")
        tree2.add_events(["e3", "e2", "e1"])

        # Different insertion order = different root
        # (unless sorted internally, which we don't do)
        assert tree1.root != tree2.root

    def test_clear(self):
        """clear removes all events."""
        tree = MerkleTree("room1")
        tree.add_events(["e1", "e2"])

        tree.clear()

        assert tree.size == 0
        assert tree.root == b"\x00" * 32

    def test_to_dict_and_from_dict(self):
        """Serialization round-trip."""
        tree1 = MerkleTree("room1")
        tree1.add_events(["e1", "e2", "e3"])

        data = tree1.to_dict()
        tree2 = MerkleTree.from_dict(data)

        assert tree2.room_id == tree1.room_id
        assert tree2.root == tree1.root
        assert tree2.get_event_ids() == tree1.get_event_ids()


class TestMerkleProof:
    """Tests for MerkleProof generation and verification."""

    def test_single_event_proof(self):
        """Proof for single event tree."""
        tree = MerkleTree("room1")
        tree.add_event("event1")

        proof = tree.get_proof("event1")

        assert proof is not None
        assert proof.event_id == "event1"
        assert len(proof.leaf_hash) == 32
        assert proof.siblings == []  # Single node, no siblings

    def test_proof_not_found(self):
        """Proof for non-existent event returns None."""
        tree = MerkleTree("room1")
        tree.add_event("event1")

        proof = tree.get_proof("event2")
        assert proof is None

    def test_proof_verification(self):
        """Generated proof verifies against tree root."""
        tree = MerkleTree("room1")
        tree.add_events(["e1", "e2", "e3", "e4"])

        proof = tree.get_proof("e2")

        assert proof is not None
        assert proof.verify(tree.root) is True

    def test_proof_fails_wrong_root(self):
        """Proof fails verification against wrong root."""
        tree = MerkleTree("room1")
        tree.add_events(["e1", "e2", "e3", "e4"])

        proof = tree.get_proof("e2")

        wrong_root = b"\xff" * 32
        assert proof.verify(wrong_root) is False

    def test_all_events_have_valid_proofs(self):
        """All events have valid proofs."""
        tree = MerkleTree("room1")
        events = [f"event{i}" for i in range(10)]
        tree.add_events(events)

        for event_id in events:
            proof = tree.get_proof(event_id)
            assert proof is not None
            assert proof.verify(tree.root) is True


class TestMerkleDiff:
    """Tests for Merkle diff operations."""

    def test_diff_with_root_match(self):
        """diff_with_root returns match when roots are same."""
        tree = MerkleTree("room1")
        tree.add_events(["e1", "e2"])

        diff = tree.diff_with_root(tree.root)

        assert diff.roots_match is True
        assert diff.local_root == diff.remote_root

    def test_diff_with_root_mismatch(self):
        """diff_with_root detects mismatch."""
        tree = MerkleTree("room1")
        tree.add_events(["e1", "e2"])

        other_root = b"\xff" * 32
        diff = tree.diff_with_root(other_root)

        assert diff.roots_match is False

    def test_diff_with_events_finds_missing(self):
        """diff_with_events finds events in remote but not local."""
        tree = MerkleTree("room1")
        tree.add_events(["e1", "e2"])

        remote_events = ["e1", "e2", "e3", "e4"]
        diff = tree.diff_with_events(remote_events)

        assert set(diff.missing_event_ids) == {"e3", "e4"}

    def test_diff_with_events_finds_extra(self):
        """diff_with_events finds events in local but not remote."""
        tree = MerkleTree("room1")
        tree.add_events(["e1", "e2", "e3", "e4"])

        remote_events = ["e1", "e2"]
        diff = tree.diff_with_events(remote_events)

        assert set(diff.extra_event_ids) == {"e3", "e4"}

    def test_diff_with_events_full_match(self):
        """diff_with_events returns empty lists when synced."""
        tree = MerkleTree("room1")
        tree.add_events(["e1", "e2", "e3"])

        remote_events = ["e1", "e2", "e3"]
        diff = tree.diff_with_events(remote_events)

        assert diff.missing_event_ids == []
        assert diff.extra_event_ids == []


class TestMerkleForest:
    """Tests for MerkleForest."""

    def test_get_tree_creates_new(self):
        """get_tree creates new tree for unknown room."""
        forest = MerkleForest()
        tree = forest.get_tree("room1")

        assert tree is not None
        assert tree.room_id == "room1"
        assert tree.size == 0

    def test_get_tree_returns_existing(self):
        """get_tree returns existing tree for known room."""
        forest = MerkleForest()
        tree1 = forest.get_tree("room1")
        tree1.add_event("e1")

        tree2 = forest.get_tree("room1")
        assert tree2 is tree1
        assert tree2.size == 1

    def test_add_event_shortcut(self):
        """add_event shortcut works."""
        forest = MerkleForest()
        forest.add_event("room1", "event1")

        assert forest.get_tree("room1").size == 1

    def test_get_root_shortcut(self):
        """get_root shortcut works."""
        forest = MerkleForest()
        forest.add_event("room1", "event1")

        root = forest.get_root("room1")
        assert root == forest.get_tree("room1").root

    def test_get_all_roots(self):
        """get_all_roots returns all room roots."""
        forest = MerkleForest()
        forest.add_event("room1", "e1")
        forest.add_event("room2", "e2")

        roots = forest.get_all_roots()

        assert "room1" in roots
        assert "room2" in roots
        assert len(roots) == 2

    def test_has_room(self):
        """has_room checks for non-empty room."""
        forest = MerkleForest()

        assert forest.has_room("room1") is False

        forest.add_event("room1", "e1")
        assert forest.has_room("room1") is True

    def test_clear_room(self):
        """clear_room removes specific room."""
        forest = MerkleForest()
        forest.add_event("room1", "e1")
        forest.add_event("room2", "e2")

        forest.clear_room("room1")

        assert forest.has_room("room1") is False
        assert forest.has_room("room2") is True

    def test_clear_all(self):
        """clear_all removes all rooms."""
        forest = MerkleForest()
        forest.add_event("room1", "e1")
        forest.add_event("room2", "e2")

        forest.clear_all()

        assert forest.get_stats()["total_rooms"] == 0

    def test_get_stats(self):
        """get_stats returns correct statistics."""
        forest = MerkleForest()
        forest.add_event("room1", "e1")
        forest.add_event("room1", "e2")
        forest.add_event("room2", "e3")

        stats = forest.get_stats()

        assert stats["total_rooms"] == 2
        assert stats["total_events"] == 3
