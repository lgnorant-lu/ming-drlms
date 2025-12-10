"""Phase 16B: Merkle Tree Module.

Implements a complete Merkle Tree for event consistency verification:
- Incremental tree construction
- Root computation and comparison
- Merkle proof generation and verification
- Range-based difference detection
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


def _hash_leaf(event_id: str) -> bytes:
    """Hash a leaf node (event ID)."""
    return hashlib.sha256(event_id.encode("utf-8")).digest()


def _hash_pair(left: bytes, right: bytes) -> bytes:
    """Hash two child nodes to create parent."""
    return hashlib.sha256(left + right).digest()


@dataclass
class MerkleProof:
    """Merkle proof for a single event.

    Contains the sibling hashes needed to verify the event is in the tree.
    """

    event_id: str
    leaf_hash: bytes
    siblings: list[tuple[bytes, bool]] = field(default_factory=list)
    # (hash, is_left) - is_left indicates if sibling is to the left

    def verify(self, root: bytes) -> bool:
        """Verify this proof against a known root.

        Args:
            root: Expected Merkle root

        Returns:
            True if proof is valid
        """
        current = self.leaf_hash
        for sibling_hash, is_left in self.siblings:
            if is_left:
                current = _hash_pair(sibling_hash, current)
            else:
                current = _hash_pair(current, sibling_hash)
        return current == root


@dataclass
class MerkleDiff:
    """Result of comparing two Merkle roots."""

    roots_match: bool
    local_root: bytes
    remote_root: bytes
    missing_event_ids: list[str] = field(default_factory=list)
    extra_event_ids: list[str] = field(default_factory=list)


class MerkleTree:
    """Merkle Tree for event consistency.

    Supports:
    - Incremental event addition
    - Root computation
    - Merkle proof generation
    - Difference detection

    Implementation uses a complete binary tree approach where:
    - Leaf nodes are hashes of event IDs
    - Internal nodes are hashes of their children
    - The tree is rebalanced on each modification
    """

    def __init__(self, room_id: str):
        """Initialize an empty Merkle tree.

        Args:
            room_id: Room identifier this tree belongs to
        """
        self.room_id = room_id
        self._leaves: list[tuple[str, bytes]] = []  # (event_id, hash)
        self._event_index: dict[str, int] = {}  # event_id -> leaf index
        self._root: Optional[bytes] = None
        self._dirty = True  # Need to rebuild tree

    @property
    def size(self) -> int:
        """Get number of events in tree."""
        return len(self._leaves)

    @property
    def root(self) -> bytes:
        """Get the current Merkle root.

        Returns empty hash if tree is empty.
        """
        if self._dirty:
            self._rebuild()
        return self._root or b"\x00" * 32

    def add_event(self, event_id: str) -> None:
        """Add an event to the tree.

        Args:
            event_id: Event ID to add
        """
        if event_id in self._event_index:
            return  # Already in tree

        leaf_hash = _hash_leaf(event_id)
        self._event_index[event_id] = len(self._leaves)
        self._leaves.append((event_id, leaf_hash))
        self._dirty = True

    def add_events(self, event_ids: list[str]) -> None:
        """Add multiple events to the tree.

        Args:
            event_ids: List of event IDs to add
        """
        for event_id in event_ids:
            self.add_event(event_id)

    def contains(self, event_id: str) -> bool:
        """Check if an event is in the tree.

        Args:
            event_id: Event ID to check

        Returns:
            True if event is in tree
        """
        return event_id in self._event_index

    def get_proof(self, event_id: str) -> Optional[MerkleProof]:
        """Generate a Merkle proof for an event.

        Args:
            event_id: Event ID to generate proof for

        Returns:
            MerkleProof or None if event not in tree
        """
        if event_id not in self._event_index:
            return None

        if self._dirty:
            self._rebuild()

        idx = self._event_index[event_id]
        leaf_hash = self._leaves[idx][1]

        # Build proof by walking up the tree
        siblings: list[tuple[bytes, bool]] = []
        n = len(self._leaves)

        if n <= 1:
            return MerkleProof(event_id=event_id, leaf_hash=leaf_hash, siblings=[])

        # Compute sibling hashes at each level
        level = [h for _, h in self._leaves]
        current_idx = idx

        while len(level) > 1:
            # Handle odd number of nodes
            if len(level) % 2 == 1:
                level.append(level[-1])  # Duplicate last

            # Find sibling
            if current_idx % 2 == 0:
                # Current is left child, sibling is right
                if current_idx + 1 < len(level):
                    siblings.append((level[current_idx + 1], False))
            else:
                # Current is right child, sibling is left
                siblings.append((level[current_idx - 1], True))

            # Move to parent level
            new_level = []
            for i in range(0, len(level), 2):
                if i + 1 < len(level):
                    new_level.append(_hash_pair(level[i], level[i + 1]))
                else:
                    new_level.append(level[i])
            level = new_level
            current_idx = current_idx // 2

        return MerkleProof(event_id=event_id, leaf_hash=leaf_hash, siblings=siblings)

    def verify_proof(self, proof: MerkleProof) -> bool:
        """Verify a Merkle proof against this tree's root.

        Args:
            proof: Proof to verify

        Returns:
            True if proof is valid for current root
        """
        return proof.verify(self.root)

    def get_event_ids(self) -> list[str]:
        """Get all event IDs in the tree.

        Returns:
            List of event IDs in insertion order
        """
        return [event_id for event_id, _ in self._leaves]

    def diff_with_root(self, remote_root: bytes) -> MerkleDiff:
        """Compare this tree's root with a remote root.

        Note: This only tells if roots match. To find actual differences,
        you need to exchange event ID sets.

        Args:
            remote_root: Remote Merkle root to compare against

        Returns:
            MerkleDiff with comparison result
        """
        local_root = self.root
        return MerkleDiff(
            roots_match=local_root == remote_root,
            local_root=local_root,
            remote_root=remote_root,
        )

    def diff_with_events(
        self, remote_event_ids: list[str], remote_root: Optional[bytes] = None
    ) -> MerkleDiff:
        """Compare this tree with a list of remote event IDs.

        Args:
            remote_event_ids: List of event IDs from remote
            remote_root: Optional remote root for verification

        Returns:
            MerkleDiff with missing and extra events
        """
        local_set = set(self._event_index.keys())
        remote_set = set(remote_event_ids)

        missing = list(remote_set - local_set)  # In remote but not local
        extra = list(local_set - remote_set)  # In local but not remote

        # Compute remote root if we have all events
        computed_remote_root = b"\x00" * 32
        if remote_root:
            computed_remote_root = remote_root
        elif remote_event_ids:
            temp_tree = MerkleTree(self.room_id + "_temp")
            temp_tree.add_events(remote_event_ids)
            computed_remote_root = temp_tree.root

        return MerkleDiff(
            roots_match=self.root == computed_remote_root,
            local_root=self.root,
            remote_root=computed_remote_root,
            missing_event_ids=missing,
            extra_event_ids=extra,
        )

    def clear(self) -> None:
        """Clear all events from the tree."""
        self._leaves.clear()
        self._event_index.clear()
        self._root = None
        self._dirty = True

    def _rebuild(self) -> None:
        """Rebuild the tree from leaves."""
        if not self._leaves:
            self._root = b"\x00" * 32
            self._dirty = False
            return

        # Build tree bottom-up
        level = [h for _, h in self._leaves]

        while len(level) > 1:
            # Handle odd number of nodes by duplicating last
            if len(level) % 2 == 1:
                level.append(level[-1])

            # Compute parent level
            new_level = []
            for i in range(0, len(level), 2):
                new_level.append(_hash_pair(level[i], level[i + 1]))
            level = new_level

        self._root = level[0]
        self._dirty = False

    def to_dict(self) -> dict:
        """Serialize tree state to dictionary.

        Returns:
            Dictionary with tree state
        """
        return {
            "room_id": self.room_id,
            "root": self.root.hex(),
            "size": self.size,
            "event_ids": self.get_event_ids(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MerkleTree":
        """Deserialize tree from dictionary.

        Args:
            data: Dictionary with tree state

        Returns:
            MerkleTree instance
        """
        tree = cls(data["room_id"])
        tree.add_events(data.get("event_ids", []))
        return tree


class MerkleForest:
    """Collection of Merkle trees, one per room.

    Provides:
    - Per-room tree management
    - Batch operations across rooms
    - Persistence support
    """

    def __init__(self):
        """Initialize an empty forest."""
        self._trees: dict[str, MerkleTree] = {}

    def get_tree(self, room_id: str) -> MerkleTree:
        """Get or create a Merkle tree for a room.

        Args:
            room_id: Room identifier

        Returns:
            MerkleTree for the room
        """
        if room_id not in self._trees:
            self._trees[room_id] = MerkleTree(room_id)
        return self._trees[room_id]

    def add_event(self, room_id: str, event_id: str) -> None:
        """Add an event to a room's tree.

        Args:
            room_id: Room identifier
            event_id: Event ID to add
        """
        self.get_tree(room_id).add_event(event_id)

    def get_root(self, room_id: str) -> bytes:
        """Get the Merkle root for a room.

        Args:
            room_id: Room identifier

        Returns:
            Merkle root (32 bytes)
        """
        return self.get_tree(room_id).root

    def get_all_roots(self) -> dict[str, bytes]:
        """Get Merkle roots for all rooms.

        Returns:
            Dictionary mapping room_id to root
        """
        return {room_id: tree.root for room_id, tree in self._trees.items()}

    def has_room(self, room_id: str) -> bool:
        """Check if a room has a tree.

        Args:
            room_id: Room identifier

        Returns:
            True if room has events
        """
        return room_id in self._trees and self._trees[room_id].size > 0

    def clear_room(self, room_id: str) -> None:
        """Clear a room's tree.

        Args:
            room_id: Room identifier
        """
        if room_id in self._trees:
            del self._trees[room_id]

    def clear_all(self) -> None:
        """Clear all trees."""
        self._trees.clear()

    def get_stats(self) -> dict[str, int]:
        """Get statistics about the forest.

        Returns:
            Dictionary with statistics
        """
        return {
            "total_rooms": len(self._trees),
            "total_events": sum(t.size for t in self._trees.values()),
        }


__all__ = [
    "MerkleProof",
    "MerkleDiff",
    "MerkleTree",
    "MerkleForest",
]
