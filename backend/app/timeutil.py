from datetime import datetime
from zoneinfo import ZoneInfo

from .config import settings


TZ = ZoneInfo(settings.timezone)


def now_local() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)


def trade_date_today() -> str:
    return datetime.now(TZ).date().isoformat()


def trade_date_of(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ).date().isoformat()


def from_unix_seconds(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=TZ).replace(tzinfo=None)


def from_unix_millis(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=TZ).replace(tzinfo=None)


def to_unix_seconds(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return int(dt.timestamp())


def format_clock(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=TZ).strftime("%H:%M:%S")

