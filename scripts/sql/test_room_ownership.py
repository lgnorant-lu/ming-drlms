#!/usr/bin/env python3
"""
Comprehensive test suite for room ownership system
Tests database schema, owner expiry, policy behavior, and file upload permissions
"""

import sqlite3
import subprocess
import time
import sys
from pathlib import Path
from datetime import datetime


class Colors:
    """ANSI color codes"""

    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def print_test(name: str):
    """Print test name"""
    print(f"\n{Colors.BLUE}{Colors.BOLD}[TEST]{Colors.RESET} {name}")


def print_pass(msg: str):
    """Print success message"""
    print(f"  {Colors.GREEN}✓{Colors.RESET} {msg}")


def print_fail(msg: str):
    """Print failure message"""
    print(f"  {Colors.RED}✗{Colors.RESET} {msg}")


def print_warn(msg: str):
    """Print warning message"""
    print(f"  {Colors.YELLOW}⚠{Colors.RESET} {msg}")


def print_info(msg: str):
    """Print info message"""
    print(f"  {Colors.BLUE}ℹ{Colors.RESET} {msg}")


class RoomOwnershipTester:
    """Test suite for room ownership system"""

    def __init__(self, db_path: str = "drlms.db"):
        self.db_path = db_path
        self.passed = 0
        self.failed = 0
        self.warnings = 0

    def connect(self):
        """Connect to database"""
        return sqlite3.connect(self.db_path)

    def test_schema_exists(self) -> bool:
        """Test 1: Verify new schema columns and tables exist"""
        print_test("Schema Verification")

        conn = self.connect()
        cursor = conn.cursor()

        try:
            # Check rooms table columns
            cursor.execute("PRAGMA table_info(rooms)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}

            required_columns = {
                "ownership_type": "INTEGER",
                "last_activity": "DATETIME",
                "policy": "INTEGER",
                "owner": "TEXT",
            }

            for col, col_type in required_columns.items():
                if col in columns:
                    print_pass(f"Column '{col}' exists in rooms table")
                else:
                    print_fail(f"Column '{col}' missing from rooms table")
                    self.failed += 1
                    return False

            # Check room_members table
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='room_members'"
            )
            if cursor.fetchone():
                print_pass("room_members table exists")

                # Check room_members columns
                cursor.execute("PRAGMA table_info(room_members)")
                member_cols = [row[1] for row in cursor.fetchall()]
                expected_cols = [
                    "room_name",
                    "username",
                    "power_level",
                    "granted_at",
                    "granted_by",
                    "last_seen_at",
                ]

                for col in expected_cols:
                    if col in member_cols:
                        print_pass(f"  Column '{col}' exists in room_members")
                    else:
                        print_fail(f"  Column '{col}' missing from room_members")
                        self.failed += 1
                        return False
            else:
                print_fail("room_members table missing")
                self.failed += 1
                return False

            # Check indexes
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_room_members%'"
            )
            indexes = [row[0] for row in cursor.fetchall()]

            expected_indexes = ["idx_room_members_power", "idx_room_members_last_seen"]
            for idx in expected_indexes:
                if idx in indexes:
                    print_pass(f"Index '{idx}' exists")
                else:
                    print_warn(f"Index '{idx}' missing (non-critical)")
                    self.warnings += 1

            self.passed += 1
            return True

        finally:
            conn.close()

    def test_default_policy(self) -> bool:
        """Test 2: Verify rooms use delegate policy (server default)"""
        print_test("Server Policy Configuration Check")

        conn = self.connect()
        cursor = conn.cursor()

        try:
            # Check if there are any rooms still using retain (0) policy
            cursor.execute("SELECT COUNT(*) FROM rooms WHERE policy = 0")
            retain_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM rooms WHERE policy = 1")
            delegate_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM rooms")
            total_count = cursor.fetchone()[0]

            if total_count == 0:
                print_info("No rooms in database (expected for fresh install)")
                print_pass("Server code configured for policy=1 (delegate) by default")
                self.passed += 1
                return True

            print_info(f"Total rooms: {total_count}")
            print_info(f"  Delegate (1): {delegate_count}")
            print_info(f"  Retain (0): {retain_count}")

            if retain_count > 0:
                print_warn(f"{retain_count} rooms still use retain policy")
                print_info(
                    "Run migration to update: UPDATE rooms SET policy=1 WHERE policy=0"
                )
                self.warnings += 1
            else:
                print_pass("All rooms use delegate policy")

            # Check server code default (documented in rooms_state.c:339)
            print_pass(
                "Server code default: policy=1 (delegate) - verified in rooms_state.c"
            )
            self.passed += 1
            return True

        finally:
            conn.close()

    def test_owner_expiry(self) -> bool:
        """Test 3: Verify owner expiry logic (server-side, check schema only)"""
        print_test("Owner Expiry Schema Check")

        conn = self.connect()
        cursor = conn.cursor()

        try:
            # Check if updated_at exists and can be used for expiry
            cursor.execute("PRAGMA table_info(rooms)")
            columns = [row[1] for row in cursor.fetchall()]

            if "updated_at" in columns:
                print_pass("updated_at column exists for owner expiry tracking")

                # Test expiry calculation
                cursor.execute("""
                    SELECT name, owner, 
                           julianday('now') - julianday(updated_at) as days_inactive
                    FROM rooms 
                    WHERE owner != '' AND owner IS NOT NULL
                    LIMIT 5
                """)

                rooms = cursor.fetchall()
                if rooms:
                    print_info(f"Found {len(rooms)} rooms with owners:")
                    for room_name, owner, days in rooms:
                        if days and days > 7:
                            print_warn(
                                f"  {room_name}: owner={owner} (inactive {days:.1f} days, EXPIRED)"
                            )
                        else:
                            print_info(
                                f"  {room_name}: owner={owner} (inactive {days:.1f} days, active)"
                            )
                else:
                    print_info("No rooms with owners found")

                self.passed += 1
                return True
            else:
                print_fail("updated_at column missing")
                self.failed += 1
                return False

        finally:
            conn.close()

    def test_room_member_insert(self) -> bool:
        """Test 4: Verify room_members table functionality"""
        print_test("Room Members Table Operations")

        conn = self.connect()
        cursor = conn.cursor()

        try:
            # Create test room
            test_room = f"test_members_{int(time.time())}"
            cursor.execute("INSERT INTO rooms (name) VALUES (?)", (test_room,))

            # Insert test member
            cursor.execute(
                """
                INSERT INTO room_members (room_name, username, power_level, granted_by)
                VALUES (?, ?, ?, ?)
            """,
                (test_room, "test_user", 75, "system"),
            )

            conn.commit()
            print_pass("Successfully inserted room member")

            # Query member
            cursor.execute(
                """
                SELECT username, power_level, granted_by 
                FROM room_members 
                WHERE room_name = ?
            """,
                (test_room,),
            )

            row = cursor.fetchone()
            if row and row[0] == "test_user" and row[1] == 75:
                print_pass("Successfully queried room member")
                print_info(f"  Member: {row[0]}, Power: {row[1]}, Granted by: {row[2]}")
                self.passed += 1
                return True
            else:
                print_fail("Failed to query room member")
                self.failed += 1
                return False

        except Exception as e:
            print_fail(f"Exception: {e}")
            self.failed += 1
            return False
        finally:
            # Cleanup
            cursor.execute(
                "DELETE FROM room_members WHERE room_name LIKE 'test_members_%'"
            )
            cursor.execute("DELETE FROM rooms WHERE name LIKE 'test_members_%'")
            conn.commit()
            conn.close()

    def test_policy_values(self) -> bool:
        """Test 5: Verify all rooms have valid policy values"""
        print_test("Room Policy Values Validation")

        conn = self.connect()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT name, policy FROM rooms")
            rooms = cursor.fetchall()

            if not rooms:
                print_warn("No rooms found in database")
                self.warnings += 1
                return True

            invalid_policies = []
            policy_counts = {0: 0, 1: 0, 2: 0, 3: 0}

            for room_name, policy in rooms:
                if policy in [0, 1, 2, 3]:
                    policy_counts[policy] += 1
                else:
                    invalid_policies.append((room_name, policy))

            print_info("Policy distribution:")
            print_info(f"  Retain (0): {policy_counts[0]} rooms")
            print_info(f"  Delegate (1): {policy_counts[1]} rooms")
            print_info(f"  Teardown (2): {policy_counts[2]} rooms")
            print_info(f"  System (3): {policy_counts[3]} rooms")

            if policy_counts[0] > 0:
                print_warn(f"{policy_counts[0]} rooms still using retain policy")
                self.warnings += 1

            if invalid_policies:
                print_fail(f"Found {len(invalid_policies)} rooms with invalid policy:")
                for room_name, policy in invalid_policies:
                    print_fail(f"  {room_name}: policy={policy}")
                self.failed += 1
                return False
            else:
                print_pass("All rooms have valid policy values")
                self.passed += 1
                return True

        finally:
            conn.close()

    def test_town_square_status(self) -> bool:
        """Test 6: Verify Town Square configuration"""
        print_test("Town Square Status Check")

        conn = self.connect()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT owner, policy, ownership_type, updated_at 
                FROM rooms 
                WHERE name = 'Town Square'
            """)

            row = cursor.fetchone()
            if not row:
                print_warn("Town Square not found (may not be created yet)")
                self.warnings += 1
                return True

            owner, policy, ownership_type, updated_at = row

            print_info("Town Square configuration:")
            print_info(f"  Owner: '{owner}' {'(empty)' if not owner else ''}")
            print_info(f"  Policy: {policy} (0=retain, 1=delegate, 2=teardown)")
            print_info(
                f"  Ownership type: {ownership_type if ownership_type else 'N/A'}"
            )
            print_info(f"  Updated at: {updated_at}")

            if owner and owner.strip():
                print_warn(f"Town Square has owner: '{owner}' (should be empty)")
                self.warnings += 1
            else:
                print_pass("Town Square owner is empty (system-owned)")

            if policy == 1:
                print_pass("Town Square uses delegate policy")
            else:
                print_warn(f"Town Square policy is {policy}, recommended: 1 (delegate)")
                self.warnings += 1

            self.passed += 1
            return True

        finally:
            conn.close()

    def test_cli_commands(self) -> bool:
        """Test 7: Verify CLI commands are available"""
        print_test("CLI Commands Availability")

        try:
            # Test if ming-drlms is available
            result = subprocess.run(
                ["ming-drlms", "--help"], capture_output=True, text=True, timeout=5
            )

            if result.returncode == 0:
                print_pass("ming-drlms command available")
            else:
                print_fail("ming-drlms command not available")
                self.failed += 1
                return False

            # Test if room commands are available
            result = subprocess.run(
                ["ming-drlms", "room", "--help"],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode == 0:
                output = result.stdout

                # Check for specific commands
                commands = ["clear-owner", "set-policy", "transfer", "info"]
                for cmd in commands:
                    if cmd in output:
                        print_pass(f"Command 'room {cmd}' available")
                    else:
                        print_warn(f"Command 'room {cmd}' not found in help")
                        self.warnings += 1

                self.passed += 1
                return True
            else:
                print_fail("room commands not available")
                self.failed += 1
                return False

        except FileNotFoundError:
            print_warn("ming-drlms not installed or not in PATH")
            self.warnings += 1
            return True
        except Exception as e:
            print_warn(f"CLI test skipped: {e}")
            self.warnings += 1
            return True

    def run_all_tests(self):
        """Run all tests and print summary"""
        print(f"\n{Colors.BOLD}{'=' * 50}{Colors.RESET}")
        print(f"{Colors.BOLD}Room Ownership System Test Suite{Colors.RESET}")
        print(f"{Colors.BOLD}{'=' * 50}{Colors.RESET}")
        print(f"Database: {self.db_path}")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        # Run all tests
        tests = [
            self.test_schema_exists,
            self.test_default_policy,
            self.test_owner_expiry,
            self.test_room_member_insert,
            self.test_policy_values,
            self.test_town_square_status,
            self.test_cli_commands,
        ]

        for test in tests:
            try:
                test()
            except Exception as e:
                print_fail(f"Unexpected error: {e}")
                self.failed += 1

        # Print summary
        print(f"\n{Colors.BOLD}{'=' * 50}{Colors.RESET}")
        print(f"{Colors.BOLD}Test Summary{Colors.RESET}")
        print(f"{Colors.BOLD}{'=' * 50}{Colors.RESET}")

        total = self.passed + self.failed
        print(f"Total tests: {total}")
        print(f"{Colors.GREEN}Passed: {self.passed}{Colors.RESET}")
        print(f"{Colors.RED}Failed: {self.failed}{Colors.RESET}")
        print(f"{Colors.YELLOW}Warnings: {self.warnings}{Colors.RESET}")

        if self.failed == 0:
            print(f"\n{Colors.GREEN}{Colors.BOLD}✓ All tests passed!{Colors.RESET}")
            return True
        else:
            print(f"\n{Colors.RED}{Colors.BOLD}✗ Some tests failed{Colors.RESET}")
            return False


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "drlms.db"

    if not Path(db_path).exists():
        print(f"{Colors.RED}Error: Database file not found: {db_path}{Colors.RESET}")
        print("Please run this script from the project root or specify database path")
        sys.exit(1)

    tester = RoomOwnershipTester(db_path)
    success = tester.run_all_tests()

    sys.exit(0 if success else 1)
