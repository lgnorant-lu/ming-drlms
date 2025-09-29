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
from typing import List, Optional
from .protocol import recv_line, recv_exact
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


def subscribe_room(sock: _socket.socket, room_name: str, since_id: int = 0) -> bool:
    """订阅房间

    Args:
        sock: TCP socket连接
        room_name: 房间名称
        since_id: 从哪个事件ID开始接收消息（可选）

    Returns:
        bool: 订阅是否成功
    """
    try:
        # 发送订阅命令: SUB|room[|since_id]
        if since_id > 0:
            cmd = f"SUB|{room_name}|{since_id}\n"
        else:
            cmd = f"SUB|{room_name}\n"

        sock.sendall(cmd.encode())

        # 接收响应
        resp = recv_line(sock)
        if resp.startswith("OK|SUB|"):
            return True
        elif resp.startswith("ERR|"):
            print(f"Subscribe room failed: {resp}")
            return False
        else:
            print(f"Unexpected subscribe response: {resp}")
            return False

    except Exception as e:
        print(f"Error subscribing to room: {e}")
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
        cmd = f"HISTORY|{room_name}|{since_id}|{limit}\n"
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


def get_available_rooms(sock: _socket.socket) -> List[RoomInfo]:
    """获取可用房间列表

    注意：这个函数需要服务器支持LIST_ROOMS命令，如果服务器不支持，
    我们可以通过尝试获取已知房间信息来实现

    Args:
        sock: TCP socket连接

    Returns:
        List[RoomInfo]: 可用房间列表
    """
    # 由于服务器可能没有LIST_ROOMS命令，我们先返回一些默认房间
    # 实际应用中，这些房间信息应该通过其他方式获取
    default_rooms = [
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

    # 尝试获取每个房间的详细信息
    rooms = []
    for room in default_rooms:
        room_info = get_room_info(sock, room.name)
        if room_info:
            rooms.append(room_info)
        else:
            # 如果获取失败，使用默认信息
            rooms.append(room)

    return rooms


__all__ = [
    "subscribe_room",
    "get_room_info",
    "send_message",
    "get_history",
    "get_available_rooms",
]
