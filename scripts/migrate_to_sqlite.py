#!/usr/bin/env python3
"""
---------------------------------------------------------------
File name:                  migrate_to_sqlite.py
Author:                     Ignorant-lu
Date created:               2025/09/28
Description:                数据迁移脚本 - 将现有文件存储迁移到SQLite数据库
----------------------------------------------------------------

Changed history:
                            2025/09/28: 初始创建;
----
"""

import sqlite3
import json
import os
import sys
from pathlib import Path
import hashlib
import shutil


class DatabaseMigrator:
    """数据迁移器"""

    def __init__(self, server_files_path: str, db_path: str = "drlms.db"):
        """初始化迁移器

        Args:
            server_files_path: server_files目录路径
            db_path: SQLite数据库文件路径
        """
        self.server_files_path = Path(server_files_path)
        self.db_path = db_path
        self.rooms_path = self.server_files_path / "rooms"

        # 备份目录
        self.backup_path = self.server_files_path / "backup_before_migration"
        self.backup_path.mkdir(exist_ok=True)

    def create_database_schema(self):
        """创建数据库表结构"""
        print("📊 创建数据库表结构...")

        db = sqlite3.connect(self.db_path)
        db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                user_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                content_hash TEXT,
                content_length INTEGER,
                content BLOB,
                file_path TEXT,
                file_size INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                name TEXT PRIMARY KEY,
                owner TEXT NOT NULL,
                policy INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_event_id INTEGER DEFAULT 0
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name TEXT NOT NULL,
                room_name TEXT NOT NULL,
                last_event_id INTEGER DEFAULT 0,
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_name, room_name)
            )
        """)

        # 创建索引
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_room_time ON events(room_name, timestamp)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_room_id ON events(room_name, id)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_sessions_user_room ON user_sessions(user_name, room_name)"
        )

        db.commit()
        db.close()
        print("✅ 数据库表结构创建完成")

    def backup_existing_data(self):
        """备份现有数据"""
        print("💾 备份现有数据...")

        # 创建一个简单的备份策略，避免递归备份问题
        backup_dir = self.backup_path / "server_files_backup"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)

        # 手动复制关键文件，而不是整个目录
        backup_dir.mkdir(parents=True)

        # 备份rooms目录下的关键文件
        rooms_src = self.server_files_path / "rooms"
        rooms_dst = backup_dir / "rooms"
        rooms_dst.mkdir()

        for room_name in os.listdir(rooms_src):
            room_src = rooms_src / room_name
            room_dst = rooms_dst / room_name

            if room_src.is_dir():
                room_dst.mkdir()

                # 备份events.log
                events_src = room_src / "events.log"
                events_dst = room_dst / "events.log"
                if events_src.exists():
                    shutil.copy2(events_src, events_dst)

                # 备份texts目录
                texts_src = room_src / "texts"
                texts_dst = room_dst / "texts"
                if texts_src.exists():
                    texts_dst.mkdir()
                    for txt_file in texts_src.glob("*.txt"):
                        shutil.copy2(txt_file, texts_dst / txt_file.name)

        print(f"✅ 数据备份完成: {backup_dir}")

    def get_room_event_count(self, room_name: str) -> int:
        """获取房间事件总数"""
        events_log = self.rooms_path / room_name / "events.log"
        if not events_log.exists():
            return 0

        count = 0
        with open(events_log, "r") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count

    def migrate_room_data(self, room_name: str):
        """迁移单个房间的数据"""
        print(f"🔄 迁移房间: {room_name}")

        room_path = self.rooms_path / room_name
        events_log = room_path / "events.log"
        texts_dir = room_path / "texts"

        if not events_log.exists():
            print(f"⚠️  房间 {room_name} 无事件日志，跳过")
            return 0

        migrated_count = 0

        with open(events_log, "r") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    # 解析JSON事件
                    event_data = json.loads(line)

                    # 读取文本内容
                    content = None
                    if event_data.get("kind") == "TEXT":
                        text_file = texts_dir / f"{event_data['event_id']}.txt"
                        if text_file.exists():
                            with open(text_file, "rb") as tf:
                                content = tf.read()
                        else:
                            print(f"⚠️  文本文件不存在: {text_file}")

                    # 验证SHA哈希
                    if content and event_data.get("sha"):
                        calculated_sha = hashlib.sha256(content).hexdigest()
                        if calculated_sha != event_data["sha"]:
                            print(
                                f"⚠️  SHA校验失败: {room_name}:{event_data['event_id']}"
                            )

                    # 插入数据库
                    db = sqlite3.connect(self.db_path)
                    db.execute(
                        """
                        INSERT INTO events (
                            room_name, event_type, user_name, timestamp,
                            content_hash, content_length, content
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            room_name,
                            event_data["kind"],
                            event_data["user"],
                            event_data["ts"],
                            event_data.get("sha"),
                            event_data.get("len"),
                            content,
                        ),
                    )
                    db.commit()
                    db.close()

                    migrated_count += 1

                    if migrated_count % 100 == 0:
                        print(f"  📈 已迁移 {migrated_count} 条记录...")

                except json.JSONDecodeError as e:
                    print(f"⚠️  JSON解析错误: {room_name}:{line_num} - {e}")
                    continue
                except Exception as e:
                    print(f"⚠️  迁移错误: {room_name}:{line_num} - {e}")
                    continue

        print(f"✅ 房间 {room_name} 迁移完成，共 {migrated_count} 条记录")
        return migrated_count

    def migrate_all_rooms(self):
        """迁移所有房间数据"""
        print("🚀 开始迁移所有房间数据...")

        total_migrated = 0
        room_dirs = [d for d in self.rooms_path.iterdir() if d.is_dir()]

        for room_dir in sorted(room_dirs):
            room_name = room_dir.name
            room_event_count = self.get_room_event_count(room_name)

            if room_event_count == 0:
                continue

            print(f"📂 处理房间: {room_name} (约 {room_event_count} 条记录)")

            migrated = self.migrate_room_data(room_name)
            total_migrated += migrated

        print(f"🎉 迁移完成！总共迁移了 {total_migrated} 条记录")

    def verify_migration(self):
        """验证迁移结果"""
        print("🔍 验证迁移结果...")

        db = sqlite3.connect(self.db_path)

        # 检查事件总数
        cursor = db.execute("SELECT COUNT(*) FROM events")
        total_events = cursor.fetchone()[0]

        # 检查房间数
        cursor = db.execute("SELECT COUNT(*) FROM rooms")
        total_rooms = cursor.fetchone()[0]

        # 检查事件类型分布
        cursor = db.execute(
            "SELECT event_type, COUNT(*) FROM events GROUP BY event_type"
        )
        event_types = cursor.fetchall()

        print("📊 迁移统计:")
        print(f"  总事件数: {total_events}")
        print(f"  房间数: {total_rooms}")
        print("  事件类型分布:")
        for event_type, count in event_types:
            print(f"    {event_type}: {count}")

        # 检查数据完整性
        cursor = db.execute(
            "SELECT COUNT(*) FROM events WHERE content IS NULL AND event_type = 'TEXT'"
        )
        missing_content = cursor.fetchone()[0]

        if missing_content > 0:
            print(f"⚠️  警告: {missing_content} 条TEXT事件缺少内容")

        db.close()

    def run_migration(self):
        """执行完整迁移流程"""
        print("🎯 开始数据库迁移流程...")

        # 1. 备份数据
        self.backup_existing_data()

        # 2. 创建数据库表结构
        self.create_database_schema()

        # 3. 迁移数据
        self.migrate_all_rooms()

        # 4. 验证结果
        self.verify_migration()

        print("🎊 迁移流程完成！")


def main():
    """主函数"""
    if len(sys.argv) != 2:
        print("用法: python migrate_to_sqlite.py <server_files路径>")
        print("示例: python migrate_to_sqlite.py server_files")
        sys.exit(1)

    server_files_path = sys.argv[1]

    if not os.path.exists(server_files_path):
        print(f"❌ 错误: 路径不存在 - {server_files_path}")
        sys.exit(1)

    print("🔧 DRLMS 数据迁移工具")
    print("=" * 50)

    migrator = DatabaseMigrator(server_files_path)
    migrator.run_migration()

    print("\n💡 提示:")
    print("  - 原始数据已备份到 backup_before_migration/ 目录")
    print("  - 新数据库文件: drlms.db")
    print("  - 迁移完成后需要修改C代码以使用SQLite存储")


if __name__ == "__main__":
    main()
