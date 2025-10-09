"""
---------------------------------------------------------------
File name:                  event_listener.py
Author:                     Ignorant-lu
Date created:               2025/09/28
Description:                后台事件监听器 - 监听服务器推送的事件
----------------------------------------------------------------

Changed history:
                            2025/09/28: 初始创建;
----
"""

from __future__ import annotations

import threading
import time
import socket as _socket
from typing import Optional, Callable, Dict
from ..state import Session
from ming_drlms.core.protocol import recv_line


class EventListener:
    """后台事件监听器"""

    def __init__(
        self,
        page,
        session: Session,
        on_message_received: Optional[
            Callable[[str, str, str, Optional[int]], None]
        ] = None,
        on_user_joined: Optional[Callable[[str, str], None]] = None,
        on_user_left: Optional[Callable[[str, str], None]] = None,
    ):
        """初始化事件监听器

        Args:
            page: Flet页面对象，用于线程安全更新UI
            session: 会话对象
            on_message_received: 消息接收回调 (room_name, user, message)
            on_user_joined: 用户加入回调 (room_name, user)
            on_user_left: 用户离开回调 (room_name, user)
        """
        self.page = page
        self.session = session
        self.on_message_received = on_message_received
        self.on_user_joined = on_user_joined
        self.on_user_left = on_user_left
        self.user_list = None  # 引用用户列表组件

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 事件处理器映射
        self._event_handlers: Dict[str, Callable] = {
            "TEXT": self._handle_text_event,
            "USER_JOIN": self._handle_user_join_event,
            "USER_LEAVE": self._handle_user_leave_event,
            "FILE": self._handle_file_event,
        }

    def start(self) -> bool:
        """启动事件监听器

        Returns:
            bool: 启动是否成功
        """
        if self._running:
            print("DEBUG: Event listener already running", flush=True)
            return True

        if not self.session.event_sock or not self.session.authed:
            print(
                "DEBUG: Cannot start event listener - no event socket or not authenticated",
                flush=True,
            )
            return False

        try:
            try:
                # 使用较短的socket超时，便于在需要时暂停监听
                self.session.event_sock.settimeout(1.0)
            except Exception:
                pass
            self._running = True
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()
            print("DEBUG: Event listener started", flush=True)
            return True
        except Exception as e:
            print(f"DEBUG: Failed to start event listener: {e}", flush=True)
            self._running = False
            return False

    def stop(self):
        """停止事件监听器"""
        if not self._running:
            return

        print("DEBUG: Stopping event listener", flush=True)
        try:
            if self.session.event_sock:
                self.session.event_sock.settimeout(0.2)
        except Exception:
            pass
        self._running = False
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)  # 等待最多2秒

        print("DEBUG: Event listener stopped", flush=True)

    def is_running(self) -> bool:
        """检查监听器是否正在运行"""
        return bool(self._running and self._thread and self._thread.is_alive())

    def _listen_loop(self):
        """监听循环"""
        print("DEBUG: Event listener loop started", flush=True)
        empty_reads = 0
        max_empty_reads = 100  # 防止无限循环

        while self._running and not self._stop_event.is_set():
            try:
                # 检查连接是否有效
                if not self.session.event_sock:
                    print("DEBUG: Event socket lost, stopping listener", flush=True)
                    break

                # 尝试接收一行数据（非阻塞）
                try:
                    line = recv_line(self.session.event_sock)
                    if line:
                        empty_reads = 0  # 重置空读计数
                        print(f"DEBUG: Raw data received: '{line}'", flush=True)

                        # 验证数据长度
                        if len(line) > 4096:  # 超过4KB的数据可能是错误的
                            print(
                                f"DEBUG: Data too long ({len(line)} chars), possible corruption",
                                flush=True,
                            )
                            continue

                        self._process_event(line)
                    else:
                        # 没有数据，短暂休眠
                        empty_reads += 1
                        if empty_reads % 50 == 0:  # 每50次空读打印一次
                            print(
                                f"DEBUG: Event listener waiting... ({empty_reads} empty reads)",
                                flush=True,
                            )
                        time.sleep(0.1)

                        # 防止无限循环
                        if empty_reads > max_empty_reads:
                            print(
                                "DEBUG: Too many empty reads, stopping listener",
                                flush=True,
                            )
                            break
                except _socket.timeout:
                    # 超时正常，继续监听
                    empty_reads += 1
                    if empty_reads % 100 == 0:  # 每100次超时打印一次
                        print(
                            f"DEBUG: Event socket timeout in listener ({empty_reads} timeouts)",
                            flush=True,
                        )
                    continue
                except ConnectionError:
                    print("DEBUG: Event connection lost in listener", flush=True)
                    break
                except Exception as e:
                    print(f"DEBUG: Error in event listener recv: {e}", flush=True)
                    time.sleep(1)  # 出错时稍等再试
                    continue

            except Exception as e:
                print(f"DEBUG: Unexpected error in event listener: {e}", flush=True)
                time.sleep(1)

        print(
            f"DEBUG: Event listener loop ended (processed {empty_reads} empty reads)",
            flush=True,
        )

    def _process_event(self, line: str):
        """处理接收到的事件"""
        line = line.strip()
        if not line:
            return

        # 过滤掉明显无效的数据
        # 1. 太短的行（事件至少需要EVT|TYPE|room格式）
        # 2. 不包含EVT|且不是特定控制消息的行
        # 3. 包含明显文件路径特征的行
        # 4. 包含调试信息特征的行
        # 5. 纯数字行（可能是时间戳）

        # 详细调试：逐个检查过滤条件
        debug_info = []

        if len(line) < 10:  # 事件格式至少需要10个字符
            debug_info.append(f"too_short({len(line)}<10)")
        if "EVT|" not in line and line not in ["READY", "OK", "END"]:
            debug_info.append("no_evt_marker")
        if any(
            pattern in line.lower()
            for pattern in [".txt", ".exe", ".png", "test_", "upload", "_test"]
        ):
            debug_info.append("file_pattern")
        # 过滤调试信息
        if any(
            pattern in line.lower()
            for pattern in ["debug", "error", "exception", "traceback", "warning"]
        ):
            debug_info.append("debug_pattern")
        # 过滤纯数字行（可能是时间戳或其他非消息内容）
        if line.isdigit() and len(line) > 10:  # 纯数字且长度超过10
            debug_info.append("pure_digits")
        # 过滤过短的纯字母行（可能是错误数据）
        if line.isalpha() and len(line) < 5:
            debug_info.append("too_short_alpha")

        if debug_info:
            print(
                f"DEBUG: Ignoring invalid event data '{line[:100]}...' - reasons: {', '.join(debug_info)}",
                flush=True,
            )
            return

        print(f"DEBUG: Received event: {line}", flush=True)

        try:
            # 查找EVT|的位置并提取事件数据
            evt_index = line.find("EVT|")
            if evt_index == -1:
                print(f"DEBUG: No EVT marker found in: {line}", flush=True)
                return

            # 提取从EVT|开始的部分
            event_data = line[evt_index:]
            print(f"DEBUG: Extracted event data: {event_data}", flush=True)

            # 解析事件格式: EVT|TYPE|room|timestamp|user|event_id|...
            parts = event_data.split("|")
            if len(parts) < 2 or parts[0] != "EVT":
                print(
                    f"DEBUG: Invalid event format after extraction: {event_data}",
                    flush=True,
                )
                return

            event_type = parts[1]

            # 验证事件类型长度（避免解析错误）
            if len(event_type) > 20:  # 事件类型应该很短
                print(
                    f"DEBUG: Event type too long, possible parsing error: {event_type}",
                    flush=True,
                )
                return

            # 验证事件类型是否有效
            valid_event_types = ["TEXT", "USER_JOIN", "USER_LEAVE", "FILE"]
            if event_type not in valid_event_types:
                print(f"DEBUG: Unknown event type '{event_type}': {line}", flush=True)
                return

            # 调用对应的事件处理器
            if event_type in self._event_handlers:
                self._event_handlers[event_type](parts)
            else:
                print(f"DEBUG: No handler for event type: {event_type}", flush=True)

        except Exception as e:
            print(f"DEBUG: Error processing event: {e}", flush=True)

    def _handle_text_event(self, parts: list):
        """处理文本消息事件"""
        try:
            # EVT|TEXT|room|timestamp|user|event_id|length|sha
            if len(parts) >= 8:
                try:
                    room_name = parts[2]
                    timestamp = parts[3]
                    user = parts[4]
                    event_id = int(parts[5])
                    length = int(parts[6])
                    sha = parts[7]

                    # 验证消息长度合理性
                    if length <= 0 or length > 65536:  # 64KB 最大限制
                        print(
                            f"DEBUG: Invalid message length: {length}, skipping",
                            flush=True,
                        )
                        return

                    # 接收消息内容的原始字节
                    try:
                        message_bytes = self._receive_bytes(length)
                        if len(message_bytes) != length:
                            print(
                                f"DEBUG: Received {len(message_bytes)} bytes, expected {length}, skipping",
                                flush=True,
                            )
                            return

                        message_text = message_bytes.decode("utf-8", errors="replace")
                        # 验证解码后的文本长度合理
                        if (
                            len(message_text) > length * 4
                        ):  # UTF-8解码后长度不应该超过4倍
                            print(
                                f"DEBUG: Decoded text too long: {len(message_text)} vs expected {length}, skipping",
                                flush=True,
                            )
                            return

                    except (ConnectionError, OSError) as e:
                        print(
                            f"DEBUG: Failed to receive message bytes: {e}", flush=True
                        )
                        return

                    # 验证SHA校验和
                    import hashlib

                    calculated_sha = hashlib.sha256(message_bytes).hexdigest()
                    if calculated_sha != sha:
                        print(
                            f"DEBUG: SHA mismatch! Expected: {sha}, Got: {calculated_sha}",
                            flush=True,
                        )
                        # 仍然继续处理，但记录警告

                    # 清理消息内容中的控制字符
                    message_text = (
                        message_text.replace("\n", " ")
                        .replace("\r", " ")
                        .replace("\t", " ")
                    )
                    # 移除多余的空格
                    message_text = " ".join(message_text.split())

                    print(
                        (
                            "DEBUG: Text event - Room: %s, User: %s, Timestamp: %s, Length: %s, SHA: %s, Message: '%s'"
                            % (room_name, user, timestamp, length, sha, message_text)
                        ),
                        flush=True,
                    )

                except (ValueError, IndexError) as e:
                    print(
                        f"DEBUG: Error parsing TEXT event parts: {e}, parts: {parts}",
                        flush=True,
                    )
                    return

                # 使用pubsub发送消息到主线程（线程安全）
                if self.on_message_received:
                    try:
                        # 通过pubsub发送消息事件
                        self.page.pubsub.send_all({
                            "type": "room_message",
                            "room_name": room_name,
                            "user": user,
                            "message": message_text,
                            "event_id": event_id
                        })
                        print(
                            f"DEBUG: Sent message via pubsub: {room_name}, {user}, event_id: {event_id}",
                            flush=True,
                        )
                    except Exception as e:
                        print(f"DEBUG: Error sending message via pubsub: {e}", flush=True)
                        # 备用方案：直接调用callback（仅用于调试）
                        try:
                            callback = self.on_message_received
                            callback(room_name, user, message_text, event_id)
                        except Exception as e2:
                            print(f"DEBUG: Error in fallback callback: {e2}", flush=True)
            else:
                print(
                    f"DEBUG: Invalid TEXT event format: {'|'.join(parts)}", flush=True
                )

        except Exception as e:
            print(f"DEBUG: Error handling text event: {e}", flush=True)

    def _receive_bytes(self, length: int) -> bytes:
        """接收指定长度的字节数据"""
        data = b""
        remaining = length

        sock = self.session.event_sock
        if sock is None:
            raise ConnectionError("Event socket unavailable")

        while remaining > 0:
            chunk = sock.recv(min(remaining, 4096))
            if not chunk:
                raise ConnectionError("Connection closed while receiving message bytes")
            data += chunk
            remaining -= len(chunk)

        return data

    def _handle_user_join_event(self, parts: list):
        """处理用户加入事件"""
        try:
            # EVT|USER_JOIN|room|timestamp|user
            if len(parts) >= 5:
                room_name = parts[2]
                user = parts[4]

                print(
                    f"DEBUG: User joined - Room: {room_name}, User: {user}", flush=True
                )

                # 使用pubsub发送用户加入事件到主线程
                if self.on_user_joined:
                    try:
                        self.page.pubsub.send_all({
                            "type": "user_join",
                            "room_name": room_name,
                            "user": user
                        })
                        print(
                            f"DEBUG: Sent user join via pubsub: {room_name}, {user}",
                            flush=True,
                        )
                    except Exception as e:
                        print(f"DEBUG: Error sending user join via pubsub: {e}", flush=True)
                        # 备用方案
                        try:
                            callback = self.on_user_joined
                            callback(room_name, user)
                        except Exception as e2:
                            print(f"DEBUG: Error in fallback user join callback: {e2}", flush=True)
            else:
                print(
                    f"DEBUG: Invalid USER_JOIN event format: {'|'.join(parts)}",
                    flush=True,
                )

        except Exception as e:
            print(f"DEBUG: Error handling user join event: {e}", flush=True)

    def _handle_user_leave_event(self, parts: list):
        """处理用户离开事件"""
        try:
            # EVT|USER_LEAVE|room|timestamp|user
            if len(parts) >= 5:
                room_name = parts[2]
                user = parts[4]

                print(f"DEBUG: User left - Room: {room_name}, User: {user}", flush=True)

                # 使用pubsub发送用户离开事件到主线程
                if self.on_user_left:
                    try:
                        self.page.pubsub.send_all({
                            "type": "user_leave",
                            "room_name": room_name,
                            "user": user
                        })
                        print(
                            f"DEBUG: Sent user leave via pubsub: {room_name}, {user}",
                            flush=True,
                        )
                    except Exception as e:
                        print(f"DEBUG: Error sending user leave via pubsub: {e}", flush=True)
                        # 备用方案
                        try:
                            callback = self.on_user_left
                            callback(room_name, user)
                        except Exception as e2:
                            print(f"DEBUG: Error in fallback user leave callback: {e2}", flush=True)
            else:
                print(
                    f"DEBUG: Invalid USER_LEAVE event format: {'|'.join(parts)}",
                    flush=True,
                )

        except Exception as e:
            print(f"DEBUG: Error handling user leave event: {e}", flush=True)

    def _handle_file_event(self, parts: list):
        """处理文件事件"""
        try:
            # EVT|FILE|room|timestamp|user|event_id|filename|size|sha
            if len(parts) >= 8:
                room_name = parts[2]
                user = parts[4]
                filename = parts[6]
                size = int(parts[7])
                sha = parts[8] if len(parts) > 8 else ""

                print(
                    (
                        "DEBUG: File event - Room: %s, User: %s, File: %s, Size: %s, SHA: %s"
                        % (room_name, user, filename, size, sha)
                    ),
                    flush=True,
                )

                # 这里可以添加文件事件处理逻辑
                # 暂时只记录日志
            else:
                print(
                    f"DEBUG: Invalid FILE event format: {'|'.join(parts)}", flush=True
                )

        except Exception as e:
            print(f"DEBUG: Error handling file event: {e}", flush=True)
