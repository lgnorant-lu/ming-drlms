"""
---------------------------------------------------------------
File name:                  room_protocol.py
Author:                     Ignorant-lu
Date created:               2025/09/28
Description:                房间和消息相关的网络协议实现
----------------------------------------------------------------

Changed history:
                            2025/09/28: 初始创建;
----
"""

from __future__ import annotations

import socket as _socket
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from .protocol import recv_line, recv_exact
from .socket_stream import SocketStream
from .types import RoomInfo


def _clean_pubt_response(response: str) -> Optional[str]:
    """清理PUBT响应，处理服务器返回的异常格式

    Args:
        response: 原始服务器响应

    Returns:
        str: 清理后的响应，如果无法清理则返回None
    """
    if not response:
        return None

    # 处理包含OK|PUBT|的响应
    if "OK|PUBT|" in response:
        # 查找OK|PUBT|的位置
        start = response.find("OK|PUBT|")
        if start != -1:
            # 提取从OK|PUBT|开始的部分
            cleaned = "OK|PUBT|" + response[start + 8 :]
            # 验证事件ID是否为有效整数
            parts = cleaned.split("|")
            if len(parts) >= 3:
                try:
                    # Validate that event ID segment is numeric
                    int(parts[2])
                    return cleaned
                except ValueError:
                    # 事件ID不是有效整数，尝试提取纯数字部分
                    event_part = parts[2]
                    # 查找连续的数字
                    match = re.search(r"\d+", event_part)
                    if match:
                        clean_event_id = match.group()
                        return f"OK|PUBT|{clean_event_id}"
                    return None
            return cleaned
        return None

    # 处理纯状态响应
    if response in ["READY", "OK"]:
        return response

    # 处理错误响应
    if response.startswith("ERR|"):
        return response

    # 处理太短的响应
    if len(response) < 3:
        return None

    return None


_POLICY_SLUG_TO_CODE = {"retain": 0, "delegate": 1, "teardown": 2}
_POLICY_CODE_TO_SLUG = {value: key for key, value in _POLICY_SLUG_TO_CODE.items()}


def policy_slug_from_code(code: int) -> Optional[str]:
    return _POLICY_CODE_TO_SLUG.get(code)


def _normalize_policy_value(policy: int | str) -> str:
    if isinstance(policy, int):
        slug = _POLICY_CODE_TO_SLUG.get(policy)
        if slug is None:
            raise ValueError(f"unknown policy code: {policy}")
        return slug
    slug = str(policy).strip().lower()
    if slug not in _POLICY_SLUG_TO_CODE:
        raise ValueError(f"unknown policy name: {policy}")
    return slug


def _readline(
    sock: _socket.socket,
    stream: Optional[SocketStream],
) -> str:
    if stream is not None:
        return stream.readline()
    return recv_line(sock)


def _readexact(
    sock: _socket.socket,
    size: int,
    stream: Optional[SocketStream],
) -> bytes:
    if stream is not None:
        return stream.readexact(size)
    return recv_exact(sock, size)


def subscribe_room(
    sock: _socket.socket,
    room_name: str,
    since_id: int = 0,
    stream: Optional[SocketStream] = None,
) -> tuple[bool, list[dict]]:
    """订阅房间，并收集在确认之前推送的事件。

    返回值: (success, backlog_events)
    backlog_events 是事件字典列表，可能包含 TEXT/USER_JOIN/USER_LEAVE 等类型。
    """

    backlog: list[dict] = []

    def _consume_event(header: str) -> None:
        parts = header.split("|")
        if len(parts) < 2 or parts[0] != "EVT":
            print(f"Unexpected subscribe response: {header}")
            return

        evt_type = parts[1]

        if evt_type == "TEXT":
            if len(parts) < 8:
                print(f"Invalid TEXT event during subscribe: {header}")
                return
            room = parts[2]
            timestamp = parts[3]
            user = parts[4]
            try:
                event_id = int(parts[5])
            except ValueError:
                event_id = None
            try:
                length = int(parts[6])
            except ValueError:
                length = 0
            sha = parts[7] if len(parts) > 7 else ""

            payload = b""
            if length > 0:
                try:
                    payload = _readexact(sock, length, stream)
                except Exception as exc:
                    print(
                        f"Failed to read TEXT payload during subscribe: {exc}",
                        flush=True,
                    )
                    return
            try:
                message = payload.decode("utf-8", errors="replace") if payload else ""
            except Exception:
                message = ""

            backlog.append(
                {
                    "type": "TEXT",
                    "room": room,
                    "timestamp": timestamp,
                    "user": user,
                    "event_id": event_id,
                    "message": message,
                    "sha": sha,
                }
            )
        elif evt_type in {"USER_JOIN", "USER_LEAVE"}:
            if len(parts) < 5:
                print(f"Invalid {evt_type} event during subscribe: {header}")
                return
            room = parts[2]
            timestamp = parts[3]
            user = parts[4]
            backlog.append(
                {
                    "type": evt_type,
                    "room": room,
                    "timestamp": timestamp,
                    "user": user,
                }
            )
        else:
            print(f"Unhandled event type during subscribe: {header}")

    try:
        if since_id > 0:
            cmd = f"SUB|{room_name}|{since_id}\n"
        else:
            cmd = f"SUB|{room_name}\n"

        sock.sendall(cmd.encode())

        while True:
            resp = _readline(sock, stream)
            if not resp:
                continue
            resp = resp.strip()
            if not resp:
                continue

            if resp.startswith("OK|SUB|") or resp.startswith("OK|SUB") or resp == "OK":
                return True, backlog

            if resp.startswith("OK|"):
                return True, backlog

            if resp.startswith("ERR|"):
                print(f"Subscribe room failed: {resp}")
                return False, backlog

            if resp.startswith("EVT|"):
                _consume_event(resp)
                continue

            print(f"Unexpected subscribe response: {resp}")
    except Exception as e:
        print(f"Error subscribing to room: {e}")
        return False, backlog

    return False, backlog


def unsubscribe_room(
    sock: _socket.socket,
    room_name: str,
    stream: Optional[SocketStream] = None,
) -> bool:
    """取消房间订阅"""

    if not room_name:
        return False

    try:
        cmd = f"UNSUB|{room_name}\n"
        sock.sendall(cmd.encode())
        resp = _readline(sock, stream)
        if resp.startswith("OK|UNSUB|"):
            return True
        if resp.startswith("ERR|"):
            print(f"Unsubscribe failed: {resp}")
            return False
        print(f"Unexpected unsubscribe response: {resp}")
        return False
    except Exception as e:
        print(f"Error unsubscribing from room: {e}")
        return False


def get_room_info(sock: _socket.socket, room_name: str) -> Optional[RoomInfo]:
    """获取房间信息

    Args:
        sock: TCP socket连接
        room_name: 房间名称

    Returns:
        RoomInfo: 房间信息，失败时返回None
    """
    try:
        # 发送房间信息查询命令: ROOMINFO|room
        cmd = f"ROOMINFO|{room_name}\n"
        sock.sendall(cmd.encode())

        # 接收响应，设置较短超时
        original_timeout = sock.gettimeout()
        sock.settimeout(3.0)

        try:
            resp = recv_line(sock)
            print(f"DEBUG: ROOMINFO response: '{resp}'", flush=True)
            if resp.startswith("OK|ROOMINFO|"):
                # 解析响应: OK|ROOMINFO|room|owner|policy|subs|last_eid
                parts = resp.split("|")
                if len(parts) >= 6:
                    room = parts[2]
                    owner = parts[3]
                    policy = int(parts[4])
                    subs = int(parts[5])
                    last_eid = int(parts[6]) if len(parts) > 6 else 0

                    return RoomInfo(
                        name=room,
                        owner=owner,
                        policy=policy,
                        subscriber_count=subs,
                        last_event_id=last_eid,
                        created_at=0,  # 服务器响应中不包含创建时间
                    )
                else:
                    print(
                        f"Invalid ROOMINFO response format (parts={len(parts)}): {resp}"
                    )
                    return None
            elif resp.startswith("ERR|"):
                print(f"Get room info failed: {resp}")
                return None
            else:
                print(f"Unexpected room info response: {resp}")
                return None
        except Exception as e:
            print(f"Error getting room info: {e}")
            return None
        finally:
            sock.settimeout(original_timeout)

    except Exception as e:
        print(f"Error getting room info: {e}")
        return None


def set_room_policy(
    sock: _socket.socket, room_name: str, policy: int | str
) -> Tuple[bool, str, Optional[int]]:
    """设置房间策略并返回结果。(success, raw_response, policy_code)"""

    if not sock:
        raise ValueError("socket is required")
    if not room_name:
        raise ValueError("room_name is required")

    slug = _normalize_policy_value(policy)

    try:
        sock.sendall(f"SETPOLICY|{room_name}|{slug}\n".encode())
        resp = recv_line(sock)
    except Exception as exc:
        return False, f"ERROR:{exc}", None

    if resp.startswith("OK|SETPOLICY") or resp == "OK":
        return True, resp, _POLICY_SLUG_TO_CODE[slug]
    return False, resp, None


def transfer_room_owner(
    sock: _socket.socket, room_name: str, new_owner: str
) -> Tuple[bool, str, Optional[str], List[str]]:
    """转移房间拥有者，返回(success, primary_response, new_owner|None, trailing_responses)."""

    if not sock:
        raise ValueError("socket is required")
    if not room_name:
        raise ValueError("room_name is required")
    if not new_owner:
        raise ValueError("new_owner is required")

    trailing: List[str] = []

    try:
        sock.sendall(f"TRANSFER|{room_name}|{new_owner}\n".encode())
        primary = recv_line(sock)
    except Exception as exc:
        return False, f"ERROR:{exc}", None, trailing

    if primary.startswith("OK|TRANSFER|"):
        parts = primary.split("|")
        granted_owner = parts[2] if len(parts) >= 3 else new_owner

        original_timeout = None
        try:
            original_timeout = sock.gettimeout()
            sock.settimeout(1.5)
        except Exception:
            original_timeout = None

        try:
            follow = recv_line(sock)
            if follow:
                trailing.append(follow)
        except Exception:
            pass
        finally:
            if original_timeout is not None:
                try:
                    sock.settimeout(original_timeout)
                except Exception:
                    pass

        return True, primary, granted_owner, trailing

    return False, primary, None, trailing


def send_message(sock: _socket.socket, room_name: str, message: str) -> bool:
    """发送消息到房间

    Args:
        sock: TCP socket连接
        room_name: 房间名称
        message: 消息内容

    Returns:
        bool: 发送是否成功
    """
    try:
        import hashlib

        # 计算消息的SHA256校验和
        message_bytes = message.encode("utf-8")
        sha256 = hashlib.sha256()
        sha256.update(message_bytes)
        sha_hex = sha256.hexdigest()

        # 发送文本消息命令: PUBT|room|len|sha
        cmd = f"PUBT|{room_name}|{len(message_bytes)}|{sha_hex}\n"

        sock.sendall(cmd.encode())

        # PUBT协议：先发送命令头，接收READY响应，然后发送消息内容，最后接收最终响应
        try:
            # 第一步：接收READY响应
            ready_resp = recv_line(sock)
            print(f"DEBUG: READY response: '{ready_resp}'", flush=True)
            if ready_resp != "READY":
                print(f"DEBUG: Expected READY but got: {ready_resp}", flush=True)
                return False

            # 第二步：发送消息内容
            sock.sendall(message_bytes)
            print(
                f"DEBUG: Sent message content ({len(message_bytes)} bytes)", flush=True
            )

            # 第三步：接收最终响应
            final_resp = recv_line(sock)
            print(f"DEBUG: Final PUBT response: '{final_resp}'", flush=True)

            if final_resp.startswith("OK|PUBT|"):
                parts = final_resp.split("|")
                if len(parts) >= 3:
                    event_id = int(parts[2])
                    print(f"Message sent successfully, event_id: {event_id}")
                    return True
                else:
                    print(f"Invalid PUBT response format: {final_resp}")
                    return False
            elif final_resp.startswith("ERR|"):
                print(f"Send message failed: {final_resp}")
                return False
            else:
                print(f"Unexpected final response: {final_resp}")
                return False

        except Exception as e:
            print(f"Error in PUBT protocol: {e}")
            return False

    except Exception as e:
        print(f"Error sending message: {e}")
        return False


def get_history(
    sock: _socket.socket, room_name: str, since_id: int = 0, limit: int = 50
) -> List[dict]:
    """获取房间历史消息

    Args:
        sock: TCP socket连接
        room_name: 房间名称
        since_id: 从哪个事件ID开始（不包含）
        limit: 最大消息数量

    Returns:
        List[dict]: 历史消息列表
    """
    try:
        # 发送历史查询命令: HISTORY|room|since_id|limit
        if since_id > 0:
            cmd = f"HISTORY|{room_name}|{limit}|{since_id}\n"
        else:
            cmd = f"HISTORY|{room_name}|{limit}\n"

        sock.sendall(cmd.encode())

        messages = []

        # 接收历史消息
        while True:
            line = recv_line(sock)
            if line.startswith("EVT|TEXT|"):
                # 解析事件: EVT|TEXT|room|ts|user|event_id|len|sha
                parts = line.split("|")
                if len(parts) >= 8:
                    room = parts[2]
                    timestamp = parts[3]
                    user = parts[4]
                    event_id = int(parts[5])
                    length = int(parts[6])
                    sha = parts[7]

                    # 接收消息内容
                    if length > 0:
                        payload = recv_exact(sock, length)
                        message_text = payload.decode("utf-8", errors="ignore")
                    else:
                        message_text = ""

                    messages.append(
                        {
                            "room": room,
                            "timestamp": timestamp,
                            "user": user,
                            "event_id": event_id,
                            "message": message_text,
                            "sha": sha,
                        }
                    )
                else:
                    print(f"Invalid EVT format: {line}")
            elif line.startswith("OK|HISTORY"):
                # 历史消息结束
                break
            elif line.startswith("ERR|"):
                print(f"Get history failed: {line}")
                break
            else:
                print(f"Unexpected history response: {line}")
                break

        return messages

    except Exception as e:
        print(f"Error getting history: {e}")
        return []


@dataclass
class RoomListPage:
    rooms: List[RoomInfo]
    offset: int
    limit: int
    total: int
    has_more: bool
    next_offset: int
    legacy_fallback: bool = False


def list_rooms(
    sock: _socket.socket, offset: int = 0, limit: int = 50
) -> RoomListPage:
    """使用 LISTROOMS 命令分页获取房间列表。

    如果服务器不支持 LISTROOMS，将回退到默认房间集合并标记 legacy_fallback。
    """

    def _parse_epoch(value: str) -> int:
        if not value or value == "-":
            return 0
        try:
            dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
            return int(dt.replace(tzinfo=timezone.utc).timestamp())
        except Exception:
            return 0

    request_offset = max(0, offset)
    request_limit = max(1, min(500, limit))

    try:
        if request_offset > 0 or request_limit != 50:
            cmd = f"LISTROOMS|{request_offset}|{request_limit}\n"
        else:
            cmd = "LISTROOMS\n"
        sock.sendall(cmd.encode())

        header = recv_line(sock)
        if not header.startswith("BEGIN|ROOMS|"):
            raise RuntimeError("Unexpected LISTROOMS header")

        total = 0
        header_parts = header.split("|")
        if len(header_parts) >= 3:
            try:
                total = int(header_parts[2])
            except ValueError:
                total = 0

        rooms: List[RoomInfo] = []
        while True:
            line = recv_line(sock)
            if line == "END|ROOMS":
                break
            if not line.startswith("ROOM|"):
                continue
            parts = line.split("|")
            if len(parts) < 8:
                continue
            try:
                policy = int(parts[3])
            except ValueError:
                policy = 0
            try:
                subscribers = int(parts[4])
            except ValueError:
                subscribers = 0
            try:
                last_event = int(parts[5])
            except ValueError:
                last_event = 0
            created_ts = _parse_epoch(parts[6])
            updated_ts = _parse_epoch(parts[7])
            rooms.append(
                RoomInfo(
                    name=parts[1],
                    owner=parts[2],
                    policy=policy,
                    subscriber_count=subscribers,
                    last_event_id=last_event,
                    created_at=created_ts,
                    updated_at=updated_ts,
                )
            )

        trailer = recv_line(sock)
        if not trailer.startswith("OK|ROOMS|"):
            raise RuntimeError("LISTROOMS missing trailer")

        trailer_parts = trailer.split("|")
        returned = len(rooms)
        has_more = False
        if len(trailer_parts) >= 3:
            try:
                returned = int(trailer_parts[2])
            except ValueError:
                returned = len(rooms)
        if len(trailer_parts) >= 4:
            has_more = trailer_parts[3] == "1"

        returned = min(returned, len(rooms))
        next_offset = request_offset + returned
        if total <= 0:
            total = max(len(rooms), next_offset)

        return RoomListPage(
            rooms=rooms,
            offset=request_offset,
            limit=request_limit,
            total=total,
            has_more=has_more,
            next_offset=next_offset,
        )
    except Exception:
        fallback_rooms = [
            RoomInfo(
                name="general",
                owner="system",
                policy=0,
                subscriber_count=0,
                last_event_id=0,
                created_at=0,
            ),
            RoomInfo(
                name="dev",
                owner="system",
                policy=0,
                subscriber_count=0,
                last_event_id=0,
                created_at=0,
            ),
            RoomInfo(
                name="design",
                owner="system",
                policy=0,
                subscriber_count=0,
                last_event_id=0,
                created_at=0,
            ),
        ]
        return RoomListPage(
            rooms=fallback_rooms,
            offset=0,
            limit=request_limit,
            total=len(fallback_rooms),
            has_more=False,
            next_offset=len(fallback_rooms),
            legacy_fallback=True,
        )


def get_available_rooms(sock: _socket.socket) -> List[RoomInfo]:
    """兼容旧调用方式，返回当前页的房间列表。"""

    page = list_rooms(sock)
    return page.rooms


__all__ = [
    "subscribe_room",
    "unsubscribe_room",
    "get_room_info",
    "set_room_policy",
    "transfer_room_owner",
    "policy_slug_from_code",
    "send_message",
    "get_history",
    "list_rooms",
    "get_available_rooms",
    "RoomListPage",
]
