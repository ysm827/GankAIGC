from datetime import datetime, timezone


def utcnow() -> datetime:
    """返回数据库兼容的 UTC naive 时间。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)
