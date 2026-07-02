from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo


CHINA_TIME_ZONE = ZoneInfo("Asia/Shanghai")


def to_china_naive(value: Optional[datetime]) -> Optional[datetime]:
    """将外部 datetime 归一为数据库兼容的北京时间 naive 值。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(CHINA_TIME_ZONE).replace(tzinfo=None)


def utc_naive_now() -> datetime:
    """返回 UTC naive 时间，用于 JWT exp 和外部 UTC 协议字段。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utcnow() -> datetime:
    """返回数据库兼容的中国时区 naive 时间。

    历史上项目用这个 helper 写入所有 DateTime 列。虽然函数名保留为
    utcnow 以减少迁移面，但业务口径现在统一为北京时间，避免数据库
    里看到的任务时间与中国用户界面相差 8 小时。
    """
    return datetime.now(CHINA_TIME_ZONE).replace(tzinfo=None)
