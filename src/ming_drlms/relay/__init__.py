"""DRLMS Relay Module.

Phase 14-15: Basic relay server
Phase 16A: Multi-relay discovery, health checking, and management
Phase 16B: Event deduplication, validation, and Merkle tree consistency
Phase 16C: Synchronization protocol with cursor persistence
Phase 16D: Offline queue and network monitoring
"""

from .server import app as app

# Phase 16A: Multi-relay support
from .discovery import (
    DiscoveryPriority,
    RelayEndpoint,
    RelayDiscovery,
)
from .health import (
    HealthScore,
    HealthChecker,
)
from .manager import (
    WriteStatus,
    WriteResult,
    ReadResult,
    RelayManager,
)
from .config import (
    RelayConfig,
    DiscoverySettings,
    HealthSettings,
    OfflineSettings,
    RelaysConfig,
    get_default_config_path,
)

# Phase 16B: Deduplication, validation, and Merkle tree
from .dedup import (
    DeduplicationStats,
    EventDeduplicator,
    RoomDeduplicator,
)
from .validator import (
    ValidationError,
    ValidationResult,
    ValidationStats,
    EventValidator,
    create_xeddsa_verifier,
)
from .merkle import (
    MerkleProof,
    MerkleDiff,
    MerkleTree,
    MerkleForest,
)

# Phase 16C: Synchronization
from .sync import (
    SyncMode,
    RelaySyncCursor,
    SyncResult,
    SyncCursorStore,
    MultiRelaySyncManager,
)

# Phase 16D: Offline queue and network monitoring
from .offline_queue import (
    QueueItemStatus,
    QueuedEvent,
    ProcessResult,
    OfflineQueue,
)
from .network import (
    NetworkEvent,
    NetworkStatus,
    NetworkMonitor,
)

__all__ = [
    # Server
    "app",
    # Discovery (16A)
    "DiscoveryPriority",
    "RelayEndpoint",
    "RelayDiscovery",
    # Health (16A)
    "HealthScore",
    "HealthChecker",
    # Manager (16A)
    "WriteStatus",
    "WriteResult",
    "ReadResult",
    "RelayManager",
    # Config (16A)
    "RelayConfig",
    "DiscoverySettings",
    "HealthSettings",
    "OfflineSettings",
    "RelaysConfig",
    "get_default_config_path",
    # Dedup (16B)
    "DeduplicationStats",
    "EventDeduplicator",
    "RoomDeduplicator",
    # Validator (16B)
    "ValidationError",
    "ValidationResult",
    "ValidationStats",
    "EventValidator",
    "create_xeddsa_verifier",
    # Merkle (16B)
    "MerkleProof",
    "MerkleDiff",
    "MerkleTree",
    "MerkleForest",
    # Sync (16C)
    "SyncMode",
    "RelaySyncCursor",
    "SyncResult",
    "SyncCursorStore",
    "MultiRelaySyncManager",
    # Offline Queue (16D)
    "QueueItemStatus",
    "QueuedEvent",
    "ProcessResult",
    "OfflineQueue",
    # Network (16D)
    "NetworkEvent",
    "NetworkStatus",
    "NetworkMonitor",
]
