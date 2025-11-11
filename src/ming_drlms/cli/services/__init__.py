"""Service layer abstractions for CLI commands."""

from .room_service import (
    RoomInfo,
    RoomService,
    RoomServiceError,
    PublishResult,
    CommandResult,
)
from .space_service import (
    SpaceService,
    SpaceServiceError,
    SpaceJoinOptions,
    SpaceJoinCallbacks,
    SpaceHistoryCallbacks,
    SpaceHistoryOptions,
)

__all__ = [
    "RoomInfo",
    "RoomService",
    "RoomServiceError",
    "PublishResult",
    "CommandResult",
    "SpaceService",
    "SpaceServiceError",
    "SpaceJoinOptions",
    "SpaceJoinCallbacks",
    "SpaceHistoryOptions",
    "SpaceHistoryCallbacks",
]
