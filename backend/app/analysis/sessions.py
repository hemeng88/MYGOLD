"""全球主要交易所的常规连续竞价时段。

原图是一张按东八区画的 24 小时钟。各所官方时间用的是本地时区，欧美还有夏令时，
所以这里存「时区 + 本地开收盘」，显示和判断开闭都按当下日期换算到 Asia/Shanghai。
只收录常规连续竞价，不含盘前盘后、集合竞价；节假日先按星期处理，不维护各国假期表。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CurvePoint
from ..timeutil import from_unix_seconds, now_local

SHANGHAI = ZoneInfo("Asia/Shanghai")
WEEKDAYS = (0, 1, 2, 3, 4)
SUN_THU = (6, 0, 1, 2, 3)

# (id, 中文名, 区域, IANA 时区, 星期, 本地时段[(开时,开分,收时,收分),...], 依据)
EXCHANGES: Tuple[tuple, ...] = (
    ("nzx", "新西兰证券交易所", "asia", "Pacific/Auckland", WEEKDAYS, ((10, 0, 16, 45),), "NZX Cash Market"),
    ("asx", "澳大利亚证券交易所", "asia", "Australia/Sydney", WEEKDAYS, ((10, 0, 16, 0),), "ASX Trade"),
    ("tse", "东京证券交易所", "asia", "Asia/Tokyo", WEEKDAYS, ((9, 0, 11, 30), (12, 30, 15, 30)), "JPX 2024-11-05 起下午收到 15:30"),
    ("sse", "上海证券交易所", "asia", "Asia/Shanghai", WEEKDAYS, ((9, 30, 11, 30), (13, 0, 15, 0)), "上交所连续竞价"),
    ("hkex", "香港证券交易所", "asia", "Asia/Hong_Kong", WEEKDAYS, ((9, 30, 16, 0),), "HKEX 已含午间延续交易"),
    ("sgx", "新加坡交易所", "asia", "Asia/Singapore", WEEKDAYS, ((9, 0, 12, 0), (13, 0, 17, 0)), "SGX Securities"),
    ("nse", "印度国家证券交易所", "asia", "Asia/Kolkata", WEEKDAYS, ((9, 15, 15, 30),), "NSE Equity"),
    ("dfm", "迪拜金融市场", "emea", "Asia/Dubai", WEEKDAYS, ((10, 0, 14, 55),), "DFM"),
    ("tadawul", "沙特证券交易所", "emea", "Asia/Riyadh", SUN_THU, ((10, 0, 15, 0),), "Tadawul 周日到周四"),
    ("jse", "约翰内斯堡证券交易所", "emea", "Africa/Johannesburg", WEEKDAYS, ((9, 0, 17, 0),), "JSE Equity"),
    ("moex", "莫斯科证券交易所", "emea", "Europe/Moscow", WEEKDAYS, ((10, 0, 18, 50),), "MOEX Equity"),
    ("lse", "伦敦证券交易所", "emea", "Europe/London", WEEKDAYS, ((8, 0, 16, 30),), "LSE Sets"),
    ("xetra", "法兰克福证券交易所", "emea", "Europe/Berlin", WEEKDAYS, ((9, 0, 17, 30),), "Xetra"),
    ("six", "瑞士证券交易所", "emea", "Europe/Zurich", WEEKDAYS, ((9, 0, 17, 30),), "SIX Swiss Exchange"),
    ("bme", "马德里证券交易所", "emea", "Europe/Madrid", WEEKDAYS, ((9, 0, 17, 30),), "BME Continuous"),
    ("stockholm", "斯德哥尔摩证券交易所", "emea", "Europe/Stockholm", WEEKDAYS, ((9, 0, 17, 30),), "Nasdaq Stockholm"),
    ("nyse", "纽交所", "americas", "America/New_York", WEEKDAYS, ((9, 30, 16, 0),), "NYSE Core Session"),
    ("nasdaq", "纳斯达克", "americas", "America/New_York", WEEKDAYS, ((9, 30, 16, 0),), "Nasdaq Regular Hours"),
    ("tsx", "多伦多证券交易所", "americas", "America/Toronto", WEEKDAYS, ((9, 30, 16, 0),), "TSX"),
    ("chx", "芝加哥证券交易所", "americas", "America/New_York", WEEKDAYS, ((9, 30, 16, 0),), "NYSE Chicago 跟纽约时段"),
    ("b3", "巴西证券交易所", "americas", "America/Sao_Paulo", WEEKDAYS, ((10, 0, 17, 0),), "B3 Equities"),
)

BANDS = (
    {"id": "asia", "label": "亚太", "color": "#7eb6d4"},
    {"id": "emea", "label": "欧非中东", "color": "#d4af37"},
    {"id": "americas", "label": "美洲", "color": "#d24b3a"},
    {"id": "overlap", "label": "欧美重叠", "color": "#c47a9a"},
    {"id": "quiet", "label": "空窗", "color": "#8c8170"},
)


def _minutes(hour: int, minute: int) -> int:
    return hour * 60 + minute


def _fmt(minutes: int) -> str:
    minutes %= 1440
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=SHANGHAI)
    return moment.astimezone(SHANGHAI)


def _to_utc8_minutes(local: datetime) -> int:
    converted = local.astimezone(SHANGHAI)
    return converted.hour * 60 + converted.minute


def _local_sessions_on(tz_name: str, sessions: Sequence[tuple], moment: datetime) -> List[Tuple[int, int]]:
    """把某所当天的本地时段换成东八区分钟数，跨午夜的拆成两段。"""
    zone = ZoneInfo(tz_name)
    local = _aware(moment).astimezone(zone)
    day = local.date()
    converted: List[Tuple[int, int]] = []
    for open_h, open_m, close_h, close_m in sessions:
        start = datetime(day.year, day.month, day.day, open_h, open_m, tzinfo=zone)
        end = datetime(day.year, day.month, day.day, close_h, close_m, tzinfo=zone)
        if end <= start:
            end += timedelta(days=1)
        start_m = _to_utc8_minutes(start)
        end_m = _to_utc8_minutes(end)
        if end_m > start_m:
            converted.append((start_m, end_m))
        else:
            converted.append((start_m, 1440))
            if end_m:
                converted.append((0, end_m))
    return converted


def _is_trading_day(weekdays: Sequence[int], tz_name: str, moment: datetime) -> bool:
    local = _aware(moment).astimezone(ZoneInfo(tz_name))
    return local.weekday() in weekdays


def _is_open(weekdays: Sequence[int], tz_name: str, sessions: Sequence[tuple], moment: datetime) -> bool:
    zone = ZoneInfo(tz_name)
    local = _aware(moment).astimezone(zone)
    if local.weekday() not in weekdays:
        return False
    clock = local.hour * 60 + local.minute
    for open_h, open_m, close_h, close_m in sessions:
        start, end = _minutes(open_h, open_m), _minutes(close_h, close_m)
        if end > start:
            if start <= clock < end:
                return True
        else:
            if clock >= start or clock < end:
                return True
    return False


def _exchange_view(row: tuple, moment: datetime) -> Dict:
    ident, name, region, tz_name, weekdays, sessions, source = row
    # 钟面永远画出常规时段；周末只把「是否开盘」关掉，不然周五沙特、周六纽交所会整圈消失
    ranges = _local_sessions_on(tz_name, sessions, moment)
    return {
        "id": ident,
        "name": name,
        "region": region,
        "timezone": tz_name,
        "source": source,
        "open": _is_open(weekdays, tz_name, sessions, moment),
        "weekend": not _is_trading_day(weekdays, tz_name, moment),
        "ranges": [{"start": _fmt(a), "end": _fmt(b), "start_min": a, "end_min": b} for a, b in ranges],
    }


def _band_of(open_regions: Iterable[str]) -> str:
    regions = set(open_regions)
    if "emea" in regions and "americas" in regions:
        return "overlap"
    if "americas" in regions:
        return "americas"
    if "emea" in regions:
        return "emea"
    if "asia" in regions:
        return "asia"
    return "quiet"


def _hour_profile(db: Session, days: int = 180) -> Tuple[List[Dict], int]:
    """把库里分钟线按东八区小时折叠：每个交易日每个小时取首尾价，看这个钟点金价多爱动。"""
    since = (now_local().date() - timedelta(days=days)).isoformat()
    rows = db.scalars(
        select(CurvePoint)
        .where(CurvePoint.trade_date >= since)
        .order_by(CurvePoint.trade_date, CurvePoint.ts)
    ).all()
    hourly: Dict[tuple, List[float]] = {}
    dates = set()
    for row in rows:
        moment = from_unix_seconds(row.ts)
        hourly.setdefault((row.trade_date, moment.hour), []).append(row.price)
        dates.add(row.trade_date)

    by_hour: Dict[int, List[float]] = defaultdict(list)
    for (_day, hour), prices in hourly.items():
        if prices[0]:
            by_hour[hour].append((prices[-1] / prices[0] - 1) * 100)

    profile = []
    for hour in range(24):
        moves = by_hour.get(hour) or []
        if not moves:
            profile.append(
                {
                    "hour": hour,
                    "label": "%02d:00" % hour,
                    "samples": 0,
                    "mean_pct": None,
                    "abs_pct": None,
                    "win_rate": None,
                }
            )
            continue
        abs_moves = [abs(v) for v in moves]
        profile.append(
            {
                "hour": hour,
                "label": "%02d:00" % hour,
                "samples": len(moves),
                "mean_pct": round(sum(moves) / len(moves), 3),
                "abs_pct": round(sum(abs_moves) / len(abs_moves), 3),
                "win_rate": round(sum(1 for value in moves if value > 0) / len(moves) * 100),
            }
        )
    return profile, len(dates)


def snapshot(db: Optional[Session] = None, moment: Optional[datetime] = None) -> Dict:
    now = _aware(moment or now_local())
    exchanges = [_exchange_view(row, now) for row in EXCHANGES]
    open_now = [item for item in exchanges if item["open"]]
    band = _band_of(item["region"] for item in open_now)
    band_meta = next(item for item in BANDS if item["id"] == band)
    profile, profile_days = _hour_profile(db, 180) if db is not None else ([], 0)
    current_hour = now.hour
    hour_row = next((row for row in profile if row["hour"] == current_hour), None)
    abs_values = [row["abs_pct"] for row in profile if row["abs_pct"] is not None]
    vol_rank = None
    if hour_row and hour_row["abs_pct"] is not None and abs_values:
        vol_rank = round(
            sum(1 for value in abs_values if value <= hour_row["abs_pct"]) / len(abs_values) * 100
        )
    return {
        "as_of": now.replace(tzinfo=None).isoformat(timespec="seconds"),
        "timezone": "Asia/Shanghai",
        "clock": now.strftime("%H:%M:%S"),
        "clock_min": now.hour * 60 + now.minute,
        "band": band,
        "band_label": band_meta["label"],
        "open_count": len(open_now),
        "open_names": [item["name"] for item in open_now],
        "exchanges": exchanges,
        "bands": list(BANDS),
        "hour_profile": profile,
        "hour_abs_pct": hour_row["abs_pct"] if hour_row else None,
        "hour_mean_pct": hour_row["mean_pct"] if hour_row else None,
        "hour_win_rate": hour_row["win_rate"] if hour_row else None,
        "hour_samples": hour_row["samples"] if hour_row else 0,
        "hour_vol_rank_pct": vol_rank,
        "profile_days": profile_days,
        "note": (
            "时段已按各所官方本地时间换算到东八区，含夏令时。"
            "东京 2024-11-05 起下午收到 15:30；港股午间已连续交易。"
        ),
    }


def current_band(moment: Optional[datetime] = None) -> str:
    now = _aware(moment or now_local())
    open_regions = [
        row[2]
        for row in EXCHANGES
        if _is_open(row[4], row[3], row[5], now)
    ]
    return _band_of(open_regions)
