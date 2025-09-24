"""
---------------------------------------------------------------
File name:                  users.py
Author:                     Ignorant-lu
Date created:               2025/09/22
Description:                用户文件(users.txt)的解析、校验、Argon2id 生成、
                            原子写入以及增删改查操作。
----------------------------------------------------------------

Changed history:
                            2025/09/22: 初始创建;
----
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from argon2 import low_level as argon2_ll


# 用户记录的内部表示： (username, kind, encoded)
# - kind: "argon2" | "legacy" | "unknown"
# - encoded:
#   - kind=="argon2": "$argon2id$..." 完整编码串
#   - kind=="legacy": "<salt>:<shahex>"
#   - kind=="unknown": 原始右侧片段（尽量保留）


USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,32}$")
ARGON2_LINE_RE = re.compile(r"^(?P<user>[^:\s][^:]*)::(?P<enc>\$argon2id\$.*)$")
LEGACY_LINE_RE = re.compile(
    r"^(?P<user>[^:\s][^:]*)\:(?P<salt>[^:\s]+)\:(?P<hash>[0-9a-fA-F]{64})$"
)


@dataclass
class Argon2Params:
    time_cost: int = 2
    memory_cost: int = 65536
    parallelism: int = 1
    hash_len: int = 32
    salt_len: int = 16


def users_file_path(data_dir: Path) -> Path:
    """Return users.txt path under given data_dir.

    Args:
        data_dir (Path): 数据目录

    Returns:
        Path: users.txt 的完整路径
    """

    return Path(data_dir) / "users.txt"


def validate_username(username: str) -> None:
    """Validate username format.

    Args:
        username (str): 待校验用户名

    Raises:
        ValueError: 不符合规则时抛出
    """

    if not USERNAME_RE.match(username or ""):
        raise ValueError(
            "invalid username: only [A-Za-z0-9_.-], length 1..32 is allowed"
        )


def parse_users(users_path: Path) -> List[Tuple[str, str, str]]:
    """Parse users.txt into list of records.

    支持三种情况：
    - 新格式：user::<argon2id_encoded_string>
    - 旧格式：user:salt:sha256hex(password+salt)
    - 其他/未知：保留右侧为 unknown

    空行与以 # 开头的注释行会被忽略。

    Args:
        users_path (Path): 文件路径

    Returns:
        list[tuple[str,str,str]]: (username, kind, encoded)
    """

    records: List[Tuple[str, str, str]] = []
    if not users_path.exists():
        return records
    try:
        for raw in users_path.read_text(errors="ignore").splitlines():
            # Trim whitespace and tolerate CRLF; keep internal spaces for robust regex
            line = raw.strip().rstrip("\r")
            if not line or line.startswith("#"):
                continue
            # 优先匹配新格式 user::<argon2id>
            m_new = ARGON2_LINE_RE.match(line)
            if m_new:
                user = m_new.group("user").strip()
                enc = m_new.group("enc").strip()
                records.append((user, "argon2", enc))
                continue
            # 尝试旧格式 user:salt:shahex（严格判定）
            # Allow optional internal spaces around ':' for legacy lines
            # Normalize by removing spaces around ':' before matching
            normalized = re.sub(r"\s*:\s*", ":", line)
            m_old = LEGACY_LINE_RE.match(normalized)
            if m_old:
                user = m_old.group("user").strip()
                salt = m_old.group("salt").strip()
                shahex = m_old.group("hash").strip()
                records.append((user, "legacy", f"{salt}:{shahex}"))
                continue
            # 兜底：unknown（尽量解析出 username:rest 的基本形态）
            colon_idx = line.find(":")
            if colon_idx != -1:
                user = line[:colon_idx].strip()
                right = line[colon_idx + 1 :].strip()
            else:
                user = line
                right = ""
            records.append((user, "unknown", right))
    except Exception:
        # 解析错误时尽量返回已解析部分
        return records
    return records


def read_auth_params_from_env() -> Dict[str, int]:
    """Read Argon2 parameters from environment with sane defaults.

    Returns:
        dict[str,int]: {time_cost, memory_cost, parallelism, hash_len, salt_len}
    """

    def getenv_int(name: str, default: int) -> int:
        v = os.environ.get(name)
        if v is None or v == "":
            return default
        try:
            return int(v)
        except Exception:
            return default

    params = Argon2Params()
    params.time_cost = getenv_int("DRLMS_ARGON2_T_COST", params.time_cost)
    params.memory_cost = getenv_int("DRLMS_ARGON2_M_COST", params.memory_cost)
    params.parallelism = getenv_int("DRLMS_ARGON2_PARALLELISM", params.parallelism)
    # hash_len / salt_len 固定默认值；如需暴露可后续扩展
    return {
        "time_cost": params.time_cost,
        "memory_cost": params.memory_cost,
        "parallelism": params.parallelism,
        "hash_len": params.hash_len,
        "salt_len": params.salt_len,
    }


def generate_argon2id_hash(
    password: str,
    *,
    time_cost: int,
    memory_cost: int,
    parallelism: int,
    hash_len: int,
    salt_len: int,
) -> str:
    """Generate Argon2id encoded string like $argon2id$... .

    Args:
        password (str): 明文密码
        time_cost (int): t_cost
        memory_cost (int): m_cost
        parallelism (int): 线程并行度 p
        hash_len (int): 输出哈希长度（bytes）
        salt_len (int): 随机盐长度（bytes）

    Returns:
        str: 形如 "$argon2id$..." 的编码串
    """

    salt = os.urandom(int(salt_len))
    encoded = argon2_ll.hash_secret(
        password.encode("utf-8"),
        salt,
        time_cost=int(time_cost),
        memory_cost=int(memory_cost),
        parallelism=int(parallelism),
        hash_len=int(hash_len),
        type=argon2_ll.Type.ID,
        version=argon2_ll.ARGON2_VERSION,
    ).decode("utf-8")
    # 规范化：argon2_cffi 已输出 $argon2id$v=19$m=...,t=...,p=...$salt$hash
    return encoded


def write_users_atomic(users_path: Path, records: List[Tuple[str, str, str]]) -> None:
    """Atomically write users.txt with given records.

    - 写入到同目录临时文件 `.users.txt.<pid>.tmp`
    - flush + os.fsync
    - 尝试 chmod 0600
    - os.replace 到目标路径
    Args:
        users_path (Path): 目标路径
        records (list): (username, kind, encoded)
    """

    users_path = Path(users_path)
    users_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = users_path.parent / f".users.txt.{os.getpid()}.tmp"
    lines: List[str] = []
    for user, kind, payload in records:
        if kind == "argon2":
            line = f"{user}::{payload}"
        elif kind == "legacy":
            # 保留读取到的 legacy 用户（CLI 不主动创建）
            line = f"{user}:{payload}"
        else:
            # unknown 尽量保留右侧片段
            if payload:
                # 若原行形式未知，兜底写作注释以避免破坏
                line = f"# unknown-format {user} {payload}"
            else:
                line = f"# unknown-format {user}"
        lines.append(line)
    data = "\n".join(lines) + ("\n" if lines else "")
    with open(tmp, "w") as f:
        f.write(data)
        f.flush()
        try:
            os.fsync(f.fileno())
        except Exception:
            pass
    try:
        os.chmod(tmp, 0o600)
    except Exception:
        pass
    os.replace(tmp, users_path)


def _find_index_by_username(records: List[Tuple[str, str, str]], username: str) -> int:
    """Find the index of the user in the records.

    Args:
        records (List[Tuple[str, str, str]]): 在记录列表中搜索的用户记录.
        username (str): 用户名.

    Returns:
        int: 用户在记录列表中的索引.
    """
    for i, (u, _k, _e) in enumerate(records):
        if u == username:
            return i
    return -1


def add_user(
    records: List[Tuple[str, str, str]], username: str, encoded: str
) -> List[Tuple[str, str, str]]:
    """Add a new user (argon2 only). Raises KeyError if exists.

    Args:
        records (List[Tuple[str, str, str]]): 记录列表.
        username (str): 用户名.
        encoded (str): 用户密码的编码串.

    Returns:
        List[Tuple[str, str, str]]: 更新后的记录列表.
    """

    validate_username(username)
    if _find_index_by_username(records, username) != -1:
        raise KeyError(f"user exists: {username}")
    return [*records, (username, "argon2", encoded)]


def set_password(
    records: List[Tuple[str, str, str]], username: str, encoded: str
) -> List[Tuple[str, str, str]]:
    """Update password for an existing user to argon2 encoding.

    Raises KeyError if user does not exist.

    Args:
        records (List[Tuple[str, str, str]]): 记录列表.
        username (str): 用户名.
        encoded (str): 用户密码的编码串.

    Returns:
        List[Tuple[str, str, str]]: 更新后的记录列表.
    """

    idx = _find_index_by_username(records, username)
    if idx == -1:
        raise KeyError(f"user not found: {username}")
    new_records = list(records)
    new_records[idx] = (username, "argon2", encoded)
    return new_records


def del_user(
    records: List[Tuple[str, str, str]], username: str
) -> List[Tuple[str, str, str]]:
    """Delete user. Raises KeyError if not exists.

    Args:
        records (List[Tuple[str, str, str]]): 记录列表.
        username (str): 用户名.

    Returns:
        List[Tuple[str, str, str]]: 更新后的记录列表.
    """

    idx = _find_index_by_username(records, username)
    if idx == -1:
        raise KeyError(f"user not found: {username}")
    new_records = list(records)
    del new_records[idx]
    return new_records
