"""M5 Phase 1 SQLite schema migration.

This script creates the room_instances table and augments existing tables
to support room sharding metadata used by the Phase 1 server refactor.

Usage:
    python scripts/m5_phase1_migration.py --db server_files/drlms.db

The script is idempotent and can be re-run safely.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from contextlib import closing


ROOM_INSTANCES_DDL = """
CREATE TABLE IF NOT EXISTS room_instances (
    instance_id TEXT PRIMARY KEY,
    room_name TEXT NOT NULL,
    storage_policy INTEGER DEFAULT 0,
    max_capacity INTEGER DEFAULT 50,
    state INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_active_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    destroyed_at DATETIME,
    last_event_id INTEGER DEFAULT 0,
    FOREIGN KEY (room_name) REFERENCES rooms(name) ON DELETE CASCADE
);
"""

FRIENDSHIPS_DDL = """
CREATE TABLE IF NOT EXISTS friendships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_a TEXT NOT NULL,
    user_b TEXT NOT NULL,
    generated_name TEXT NOT NULL,
    word_bank_version TEXT,
    established_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_a, user_b),
    CHECK(user_a < user_b)
);
"""

FRIEND_NOTES_DDL = """
CREATE TABLE IF NOT EXISTS friend_notes (
    friendship_id INTEGER NOT NULL,
    owner TEXT NOT NULL,
    note TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (friendship_id, owner),
    FOREIGN KEY (friendship_id) REFERENCES friendships(id)
        ON DELETE CASCADE
);
"""


def column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    cursor.execute("PRAGMA table_info(%s)" % table)
    return any(row[1] == column for row in cursor.fetchall())


def create_room_instances(cursor: sqlite3.Cursor) -> None:
    cursor.execute(ROOM_INSTANCES_DDL)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_room_instances_name "
        "ON room_instances(room_name)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_room_instances_state ON room_instances(state)"
    )


def ensure_rooms_columns(cursor: sqlite3.Cursor) -> None:
    additions = [
        ("storage_policy_template", "INTEGER DEFAULT 0"),
        ("max_capacity_per_instance", "INTEGER DEFAULT 50"),
        ("max_instances", "INTEGER DEFAULT 20"),
        ("total_instances", "INTEGER DEFAULT 0"),
        ("total_subs", "INTEGER DEFAULT 0"),
        ("max_ephemeral_events", "INTEGER DEFAULT 1000"),
    ]
    for column, ddl in additions:
        if not column_exists(cursor, "rooms", column):
            cursor.execute(f"ALTER TABLE rooms ADD COLUMN {column} {ddl}")


def ensure_events_instance(cursor: sqlite3.Cursor) -> None:
    if not column_exists(cursor, "events", "instance_id"):
        cursor.execute("ALTER TABLE events ADD COLUMN instance_id TEXT")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_instance_id ON events(instance_id)"
        )


def ensure_events_display_token(cursor: sqlite3.Cursor) -> None:
    if not column_exists(cursor, "events", "display_token"):
        cursor.execute("ALTER TABLE events ADD COLUMN display_token TEXT DEFAULT ''")
    cursor.execute(
        "UPDATE events SET display_token = user_name "
        "WHERE display_token IS NULL OR display_token = ''"
    )


def migrate_user_sessions(cursor: sqlite3.Cursor) -> None:
    if column_exists(cursor, "user_sessions", "instance_id"):
        return
    cursor.execute(
        """
        CREATE TABLE user_sessions_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT NOT NULL,
            room_name TEXT NOT NULL,
            instance_id TEXT NOT NULL,
            last_event_id INTEGER DEFAULT 0,
            joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_name, room_name, instance_id)
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO user_sessions_new (user_name, room_name, instance_id,
                                       last_event_id, joined_at)
        SELECT user_name,
               room_name,
               'legacy-' || room_name,
               last_event_id,
               joined_at
        FROM user_sessions
        """
    )
    cursor.execute("DROP TABLE user_sessions")
    cursor.execute("ALTER TABLE user_sessions_new RENAME TO user_sessions")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_sessions_user_room_instance "
        "ON user_sessions(user_name, room_name, instance_id)"
    )


def ensure_friendships(cursor: sqlite3.Cursor) -> None:
    cursor.execute(FRIENDSHIPS_DDL)
    if not column_exists(cursor, "friendships", "generated_name"):
        cursor.execute("ALTER TABLE friendships ADD COLUMN generated_name TEXT")
    if not column_exists(cursor, "friendships", "word_bank_version"):
        cursor.execute("ALTER TABLE friendships ADD COLUMN word_bank_version TEXT")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_friendships_user_a ON friendships(user_a)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_friendships_user_b ON friendships(user_b)"
    )


def ensure_friend_notes(cursor: sqlite3.Cursor) -> None:
    cursor.execute(FRIEND_NOTES_DDL)


def run_migration(db_path: str) -> None:
    if not os.path.exists(db_path):
        parent = os.path.dirname(db_path) or "."
        os.makedirs(parent, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as conn:
        conn.isolation_level = None
        with conn:
            cursor = conn.cursor()
            create_room_instances(cursor)
            ensure_rooms_columns(cursor)
            ensure_events_instance(cursor)
            ensure_events_display_token(cursor)
            migrate_user_sessions(cursor)
            ensure_friendships(cursor)
            ensure_friend_notes(cursor)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="M5 Phase 1 SQLite migration")
    parser.add_argument(
        "--db",
        default=os.path.join("server_files", "drlms.db"),
        help="Path to drlms SQLite database (default: server_files/drlms.db)",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        run_migration(args.db)
    except sqlite3.DatabaseError as exc:  # pragma: no cover - logging only
        sys.stderr.write(f"migration failed: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
