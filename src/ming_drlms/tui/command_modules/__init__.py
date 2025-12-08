from __future__ import annotations

from .room import register_room_commands
from .file import register_file_commands
from .e2ee import register_e2ee_commands
from .system import register_system_commands
from .user import register_user_commands
from .identity import register_identity_commands
from .contacts import register_contact_commands


def register_all(handler) -> None:
    register_room_commands(handler)
    register_file_commands(handler)
    register_e2ee_commands(handler)
    register_system_commands(handler)
    register_user_commands(handler)
    register_identity_commands(handler)  # Phase 15A
    register_contact_commands(handler)  # Phase 15B
