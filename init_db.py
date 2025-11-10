#!/usr/bin/env python3
"""
Initialize SQLite database to match current code schema
"""

import sqlite3


def create_database():
    """Create SQLite database with correct schema"""

    # Create database connection
    conn = sqlite3.connect("drlms.db")
    cursor = conn.cursor()

    try:
        # Create events table with instance_id column
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                user_name TEXT NOT NULL,
                display_token TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                content_hash TEXT,
                content_length INTEGER,
                content BLOB,
                file_path TEXT,
                file_size INTEGER,
                instance_id TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create rooms table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                name TEXT PRIMARY KEY,
                owner TEXT,
                policy INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_event_id INTEGER DEFAULT 0,
                storage_policy_template INTEGER DEFAULT 0,
                max_capacity_per_instance INTEGER DEFAULT 50,
                max_instances INTEGER DEFAULT 20,
                total_instances INTEGER DEFAULT 0,
                total_subs INTEGER DEFAULT 0,
                max_ephemeral_events INTEGER DEFAULT 1000
            )
        """)

        # Create room_instances table
        cursor.execute("""
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
            )
        """)

        # Create user_sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name TEXT NOT NULL,
                room_name TEXT NOT NULL,
                display_token TEXT NOT NULL,
                instance_id TEXT NOT NULL,
                last_event_id INTEGER DEFAULT 0,
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (room_name) REFERENCES rooms(name) ON DELETE CASCADE,
                FOREIGN KEY (instance_id) REFERENCES room_instances(instance_id) ON DELETE CASCADE,
                UNIQUE(user_name, room_name, instance_id)
            )
        """)

        # Create refresh_tokens table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                token TEXT PRIMARY KEY,
                user_name TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create friendships table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS friendships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_a TEXT NOT NULL,
                user_b TEXT NOT NULL,
                generated_name TEXT NOT NULL,
                word_bank_version TEXT NOT NULL,
                established_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_a, user_b)
            )
        """)

        # Create friend_notes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS friend_notes (
                friendship_id INTEGER NOT NULL,
                owner TEXT NOT NULL,
                note TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (friendship_id, owner),
                FOREIGN KEY (friendship_id) REFERENCES friendships(id) ON DELETE CASCADE
            )
        """)

        # Create indexes
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_events_room_time ON events(room_name, timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_events_room_id ON events(room_name, id)",
            "CREATE INDEX IF NOT EXISTS idx_events_instance_id ON events(instance_id)",
            "CREATE INDEX IF NOT EXISTS idx_user_sessions_user_room ON user_sessions(user_name, room_name)",
            "CREATE INDEX IF NOT EXISTS idx_user_sessions_instance ON user_sessions(instance_id)",
            "CREATE INDEX IF NOT EXISTS idx_room_instances_room ON room_instances(room_name)",
            "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_name)",
        ]

        for index_sql in indexes:
            cursor.execute(index_sql)

        # Commit changes
        conn.commit()
        print("[OK] Database schema created successfully")

        # Verify table structure
        cursor.execute("PRAGMA table_info(events)")
        events_columns = [row[1] for row in cursor.fetchall()]
        print(f"[OK] Events table columns: {events_columns}")

        if "instance_id" in events_columns:
            print("[OK] instance_id column successfully added")
        else:
            print("[ERROR] instance_id column missing")
            return False

        return True

    except Exception as e:
        print(f"[ERROR] Failed to create database: {e}")
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    print("=== Initializing SQLite Database ===")
    if create_database():
        print("[SUCCESS] Database initialization completed")
    else:
        print("[FAILED] Database initialization failed")
        exit(1)
