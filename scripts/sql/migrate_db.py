#!/usr/bin/env python3
"""
Database migration script for room ownership system
Adds new fields and tables to existing database
"""

import sqlite3
import sys
from datetime import datetime


def backup_database(db_path: str) -> str:
    """Create database backup"""
    import shutil

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.backup.{timestamp}"
    try:
        shutil.copy2(db_path, backup_path)
        print(f"[OK] Database backed up to: {backup_path}")
        return backup_path
    except Exception as e:
        print(f"[ERROR] Failed to backup database: {e}")
        sys.exit(1)


def check_column_exists(cursor, table: str, column: str) -> bool:
    """Check if column exists in table"""
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns


def check_table_exists(cursor, table: str) -> bool:
    """Check if table exists"""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cursor.fetchone() is not None


def migrate_database(db_path: str = "drlms.db") -> bool:
    """Migrate existing database to new schema"""

    print("=== Database Migration Script ===")
    print(f"Target: {db_path}")
    print()

    # Backup first
    backup_path = backup_database(db_path)

    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 1. Add new columns to rooms table
        print("[1/10] Checking rooms table columns...")

        if not check_column_exists(cursor, "rooms", "ownership_type"):
            print("  → Adding ownership_type column...")
            cursor.execute(
                "ALTER TABLE rooms ADD COLUMN ownership_type INTEGER DEFAULT 0"
            )
            print("  ✓ Added ownership_type")
        else:
            print("  ✓ ownership_type already exists")

        if not check_column_exists(cursor, "rooms", "last_activity"):
            print("  → Adding last_activity column...")
            # SQLite doesn't support non-constant defaults in ALTER TABLE
            # So we add NULL first, then UPDATE
            cursor.execute("ALTER TABLE rooms ADD COLUMN last_activity DATETIME")
            cursor.execute(
                "UPDATE rooms SET last_activity = CURRENT_TIMESTAMP WHERE last_activity IS NULL"
            )
            print("  ✓ Added last_activity")
        else:
            print("  ✓ last_activity already exists")

        # 2. Create room_members table
        print("\n[2/10] Checking room_members table...")
        if not check_table_exists(cursor, "room_members"):
            print("  → Creating room_members table...")
            cursor.execute("""
                CREATE TABLE room_members (
                    room_name TEXT NOT NULL,
                    username TEXT NOT NULL,
                    power_level INTEGER DEFAULT 10,
                    granted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    granted_by TEXT,
                    last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (room_name, username),
                    FOREIGN KEY (room_name) REFERENCES rooms(name) ON DELETE CASCADE
                )
            """)
            print("  ✓ Created room_members table")
        else:
            print("  ✓ room_members table already exists")

        # 3. Create relay_events table (server-side encrypted events)
        print("\n[3/10] Checking relay_events table...")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS relay_events (
                room TEXT NOT NULL,
                server_seq INTEGER NOT NULL,
                server_ts INTEGER NOT NULL,
                ciphertext BLOB NOT NULL,
                client_hash TEXT,
                content_len INTEGER,
                PRIMARY KEY (room, server_seq)
            )
            """
        )
        print("  ✓ relay_events table exists")

        # 4. Create room_seq table (per-room sequence allocator)
        print("\n[4/10] Checking room_seq table...")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS room_seq (
                room TEXT PRIMARY KEY,
                seq INTEGER NOT NULL
            )
            """
        )
        print("  ✓ room_seq table exists")

        # 5. Create client_events table (local decrypted events)
        print("\n[5/10] Checking client_events table...")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS client_events (
                room TEXT NOT NULL,
                server_seq INTEGER,
                ts INTEGER NOT NULL,
                sender_id TEXT NOT NULL,
                device_id INTEGER NOT NULL,
                content_type TEXT NOT NULL,
                content_bytes BLOB,
                signature BLOB NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0,
                client_hash TEXT,
                PRIMARY KEY (room, ts, sender_id, device_id)
            )
            """
        )
        print("  ✓ client_events table exists")

        # 6. Create client_sync_state table (since_seq tracking)
        print("\n[6/10] Checking client_sync_state table...")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS client_sync_state (
                room TEXT PRIMARY KEY,
                last_seen_seq INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        print("  ✓ client_sync_state table exists")

        # 7. Create indexes
        print("\n[7/10] Creating indexes...")
        indexes = [
            (
                "idx_room_members_power",
                "CREATE INDEX IF NOT EXISTS idx_room_members_power ON room_members(room_name, power_level DESC)",
            ),
            (
                "idx_room_members_last_seen",
                "CREATE INDEX IF NOT EXISTS idx_room_members_last_seen ON room_members(room_name, last_seen_at DESC)",
            ),
            (
                "idx_relay_events_room_seq",
                "CREATE INDEX IF NOT EXISTS idx_relay_events_room_seq ON relay_events(room, server_seq)",
            ),
            (
                "idx_relay_events_room_ts",
                "CREATE INDEX IF NOT EXISTS idx_relay_events_room_ts ON relay_events(room, server_ts)",
            ),
            (
                "idx_client_events_room_ts",
                "CREATE INDEX IF NOT EXISTS idx_client_events_room_ts ON client_events(room, ts)",
            ),
            (
                "idx_client_events_room_seq",
                "CREATE INDEX IF NOT EXISTS idx_client_events_room_seq ON client_events(room, server_seq)",
            ),
        ]

        for idx_name, idx_sql in indexes:
            cursor.execute(idx_sql)
            print(f"  ✓ Created index: {idx_name}")

        # 8. Update existing rooms to use delegate policy
        print("\n[8/10] Updating room policies...")
        cursor.execute("SELECT COUNT(*) FROM rooms WHERE policy = 0")
        retain_count = cursor.fetchone()[0]

        if retain_count > 0:
            print(f"  → Found {retain_count} rooms with retain policy")
            print("  → Updating to delegate policy...")
            cursor.execute("UPDATE rooms SET policy = 1 WHERE policy = 0")
            print(f"  ✓ Updated {retain_count} rooms to delegate policy")
        else:
            print("  ✓ No rooms need policy update")

        # 9. Clear expired owners
        print("\n[9/10] Checking for expired owners...")
        cursor.execute("""
            SELECT name, owner, 
                   julianday('now') - julianday(updated_at) as days_inactive
            FROM rooms 
            WHERE owner != '' AND owner IS NOT NULL
        """)

        expired_rooms = []
        for row in cursor.fetchall():
            room_name, owner, days_inactive = row
            if days_inactive and days_inactive > 7:
                expired_rooms.append((room_name, owner, days_inactive))

        if expired_rooms:
            print(f"  → Found {len(expired_rooms)} rooms with expired owners:")
            for room_name, owner, days in expired_rooms:
                print(
                    f"    - {room_name}: owner={owner} (inactive for {days:.1f} days)"
                )

            print("  → Clearing expired owners...")
            for room_name, _, _ in expired_rooms:
                cursor.execute(
                    "UPDATE rooms SET owner = '', updated_at = CURRENT_TIMESTAMP WHERE name = ?",
                    (room_name,),
                )
            print(f"  ✓ Cleared {len(expired_rooms)} expired owners")
        else:
            print("  ✓ No expired owners found")

        # 10. Commit changes
        print("\n[10/10] Committing changes...")
        conn.commit()
        print("  ✓ All changes committed")

        # Verify migration
        print("\n=== Migration Verification ===")
        cursor.execute("PRAGMA table_info(rooms)")
        rooms_columns = [row[1] for row in cursor.fetchall()]
        print(f"Rooms table columns: {', '.join(rooms_columns)}")

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        print(f"Tables: {', '.join(tables)}")

        cursor.execute("SELECT COUNT(*) FROM rooms")
        room_count = cursor.fetchone()[0]
        print(f"Total rooms: {room_count}")

        if check_table_exists(cursor, "room_members"):
            cursor.execute("SELECT COUNT(*) FROM room_members")
            member_count = cursor.fetchone()[0]
            print(f"Room members: {member_count}")

        print("\n" + "=" * 40)
        print("[SUCCESS] Migration completed successfully!")
        print(f"Backup saved at: {backup_path}")
        print("=" * 40)

        return True

    except Exception as e:
        print(f"\n[ERROR] Migration failed: {e}")
        print(f"Database backup available at: {backup_path}")
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = "drlms.db"

    if migrate_database(db_path):
        sys.exit(0)
    else:
        sys.exit(1)
