from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Union


def parse_iso_timestamp(value: Optional[str]) -> datetime:
    """解析 ISO8601 字符串为本地时间的 datetime 实例。"""
    if not value:
        return datetime.now()

    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return datetime.now()

    if parsed.tzinfo is None:
        # 默认视为 UTC，再转换到本地时区
        parsed = parsed.replace(tzinfo=timezone.utc)

    local_dt = parsed.astimezone().replace(tzinfo=None)
    return local_dt


def format_chat_timestamp(
    value: Optional[Union[str, datetime]], now: Optional[datetime] = None
) -> str:
    """根据聊天规则格式化时间戳。

    规则：
    - 当天：HH:mm
    - 昨天："昨天 HH:mm"
    - 前天："前天 HH:mm"
    - 三天前："3天前 HH:mm"
    - 超过三天且同年："MM-DD HH:mm"
    - 不同年份："YYYY-MM-DD HH:mm"
    """

    if isinstance(value, datetime):
        timestamp = value
    else:
        timestamp = parse_iso_timestamp(value)

    if now is None:
        now = datetime.now()

    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone().replace(tzinfo=None)

    today = now.date()
    msg_date = timestamp.date()
    delta_days = (today - msg_date).days

    time_part = timestamp.strftime("%H:%M")

    if delta_days <= 0:
        return time_part
    if delta_days == 1:
        return f"昨天 {time_part}"
    if delta_days == 2:
        return f"前天 {time_part}"
    if delta_days == 3:
        return f"3天前 {time_part}"
    if timestamp.year == now.year:
        return timestamp.strftime("%m-%d %H:%M")
    return timestamp.strftime("%Y-%m-%d %H:%M")
