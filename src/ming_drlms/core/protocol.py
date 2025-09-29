"""
---------------------------------------------------------------
File name:                  protocol.py
Author:                     Ignorant-lu
Date created:               2025/09/28
Description:                底层网络协议原语实现
----------------------------------------------------------------

Changed history:
                            2025/09/28: 初始创建;
----
"""

from __future__ import annotations

import socket as _socket


def tcp_connect(host: str, port: int, timeout: float = 5.0) -> _socket.socket:
    """建立TCP连接

    Args:
        host: 主机地址
        port: 端口号
        timeout: 连接超时时间（秒）

    Returns:
        socket: 已连接的socket对象

    Raises:
        ConnectionError: 连接失败时抛出
    """
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((host, port))
    return s


def recv_line(sock: _socket.socket) -> str:
    """接收一行数据（以换行符结尾）

    Args:
        sock: socket连接

    Returns:
        str: 接收到的行数据（不包含换行符）

    Raises:
        ConnectionError: 连接断开时抛出
    """
    data = b""
    while True:
        chunk = sock.recv(1)
        if not chunk:
            raise ConnectionError("Connection closed by peer")
        if chunk == b"\n":
            break
        data += chunk
    return data.decode("utf-8", errors="ignore")


def recv_exact(sock: _socket.socket, size: int) -> bytes:
    """接收指定字节数的数据

    Args:
        sock: socket连接
        size: 要接收的字节数

    Returns:
        bytes: 接收到的数据

    Raises:
        ConnectionError: 连接断开或数据不完整时抛出
    """
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("Connection closed by peer")
        data += chunk
    return data


def login(sock: _socket.socket, user: str, password: str) -> bool:
    """用户登录

    Args:
        sock: socket连接
        user: 用户名
        password: 密码

    Returns:
        bool: 登录是否成功
    """
    try:
        sock.sendall(f"LOGIN|{user}|{password}\n".encode())
        resp = recv_line(sock)
        return resp.startswith("OK|") or resp == "OK"
    except Exception:
        return False


__all__ = [
    "tcp_connect",
    "recv_line",
    "recv_exact",
    "login",
]
