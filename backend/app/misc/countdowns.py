"""倒计时：单次日期（游戏发售）或每月循环（发工资）。

时刻可空。空着就按「整天」算：当天 0 点起算即将到来，当天之内显示「今天」，
过了夜里 12 点才翻到下一轮。填了时刻就精确倒数到那一分。

每月 31 号在只有 28/30 天的月份落到当月最后一天，避免 2 月直接跳空。
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CountdownItem
from ..timeutil import now_local, to_unix_seconds
from .holidays import next_holiday

KIND_ONCE = "once"
KIND_MONTHLY = "monthly"
KIND_HOLIDAY = "holiday"
KINDS = (KIND_ONCE, KIND_MONTHLY)
HOLIDAY_ITEM_ID = -1
TITLE_MAX = 40
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_ITEMS = 50


def _today(now: datetime) -> date:
    return now.date()


def _at(day: date, hour: Optional[int], minute: Optional[int]) -> datetime:
    return datetime(day.year, day.month, day.day, hour or 0, minute or 0)


def _has_time(hour: Optional[int]) -> bool:
    return hour is not None


def _clamp_day(year: int, month: int, day: int) -> int:
    return min(day, calendar.monthrange(year, month)[1])


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _monthly_on(year: int, month: int, day: int, hour: Optional[int], minute: Optional[int]) -> datetime:
    return _at(date(year, month, _clamp_day(year, month, day)), hour, minute)


def resolve(
    kind: str,
    once_date: Optional[str],
    month_day: Optional[int],
    hour: Optional[int],
    minute: Optional[int],
    now: Optional[datetime] = None,
) -> dict:
    now = now or now_local()
    today = _today(now)

    if kind == KIND_ONCE:
        if not once_date:
            raise ValueError("单次倒计时要填日期")
        target_day = date.fromisoformat(once_date)
        target = _at(target_day, hour, minute)
        if today < target_day:
            status = "upcoming"
        elif today == target_day:
            status = "past" if _has_time(hour) and now >= target else "today"
        else:
            status = "past"
        return _pack(target, status, now)

    if kind != KIND_MONTHLY:
        raise ValueError("类型只能是 once 或 monthly")
    if not month_day:
        raise ValueError("每月循环要填几号")

    this = _monthly_on(today.year, today.month, month_day, hour, minute)
    this_day = this.date()
    if today < this_day:
        target, status = this, "upcoming"
    elif today == this_day:
        if _has_time(hour) and now >= this:
            y, m = _shift_month(today.year, today.month, 1)
            target, status = _monthly_on(y, m, month_day, hour, minute), "upcoming"
        else:
            target, status = this, "today"
    else:
        y, m = _shift_month(today.year, today.month, 1)
        target, status = _monthly_on(y, m, month_day, hour, minute), "upcoming"
    return _pack(target, status, now)


def _pack(target: datetime, status: str, now: datetime) -> dict:
    next_ts = to_unix_seconds(target)
    now_ts = to_unix_seconds(now)
    remaining = max(0, next_ts - now_ts) if status != "past" else 0
    if status == "today" and not remaining:
        remaining = 0
    elapsed_days = (now.date() - target.date()).days if status == "past" else None
    return {
        "next_date": target.date().isoformat(),
        "next_ts": next_ts,
        "status": status,
        "remaining_seconds": remaining,
        "elapsed_days": elapsed_days,
    }


def rule_label(kind: str, once_date: Optional[str], month_day: Optional[int], hour: Optional[int], minute: Optional[int]) -> str:
    clock = ""
    if hour is not None:
        clock = " %02d:%02d" % (hour, minute or 0)
    if kind == KIND_ONCE:
        return "%s%s" % (once_date or "", clock)
    return "每月 %d 日%s" % (month_day or 0, clock)


def validate_payload(title: str, kind: str, once_date: Optional[str], month_day: Optional[int], hour: Optional[int], minute: Optional[int]) -> dict:
    cleaned = (title or "").strip()
    if not cleaned:
        raise ValueError("先起个名字")
    if len(cleaned) > TITLE_MAX:
        raise ValueError("名字最多 %d 个字" % TITLE_MAX)
    if kind not in KINDS:
        raise ValueError("类型只能是单次或每月")

    date_s = (once_date or "").strip() or None
    day = month_day
    if kind == KIND_ONCE:
        if not date_s or not DATE_RE.match(date_s):
            raise ValueError("日期格式不对，应该是 2026-12-15")
        try:
            date.fromisoformat(date_s)
        except ValueError as exc:
            raise ValueError("没有这一天") from exc
        day = None
    else:
        if day is None or not (1 <= int(day) <= 31):
            raise ValueError("每月循环填 1 到 31 号")
        day = int(day)
        date_s = None

    if hour is None and minute is None:
        hh = mm = None
    elif hour is None or not (0 <= int(hour) <= 23):
        raise ValueError("小时是 0 到 23")
    else:
        hh = int(hour)
        mm = int(minute or 0)
        if not (0 <= mm <= 59):
            raise ValueError("分钟是 0 到 59")

    return {"title": cleaned, "kind": kind, "date": date_s, "day": day, "hour": hh, "minute": mm}


def _to_out(row: CountdownItem, now: datetime) -> dict:
    computed = resolve(row.kind, row.date, row.day, row.hour, row.minute, now)
    return {
        "id": row.id,
        "title": row.title,
        "kind": row.kind,
        "date": row.date,
        "day": row.day,
        "hour": row.hour,
        "minute": row.minute,
        "builtin": False,
        "rule_label": rule_label(row.kind, row.date, row.day, row.hour, row.minute),
        **computed,
    }


def _holiday_item(now: datetime) -> Optional[dict]:
    found = next_holiday(now.date())
    if found is None:
        return None
    packed = _pack(_at(found["start"], None, None), found["status"], now)
    start = found["start"].isoformat()
    end = found["end"].isoformat()
    return {
        "id": HOLIDAY_ITEM_ID,
        "title": found["name"],
        "kind": KIND_HOLIDAY,
        "date": start,
        "day": None,
        "hour": None,
        "minute": None,
        "builtin": True,
        "rule_label": "法定假 · %s 至 %s · 共 %d 天" % (start, end, found["days"]),
        **packed,
    }


def _sort_key(item: dict) -> tuple:
    if item["status"] == "today":
        return (0, item["next_ts"])
    if item["status"] == "upcoming":
        return (1, item["next_ts"])
    return (2, -item["next_ts"])


def list_countdowns(db: Session, user_id: int, now: Optional[datetime] = None) -> List[dict]:
    now = now or now_local()
    rows = list(
        db.scalars(
            select(CountdownItem)
            .where(CountdownItem.user_id == user_id)
            .order_by(CountdownItem.id.asc())
        ).all()
    )
    items = [_to_out(row, now) for row in rows]
    holiday = _holiday_item(now)
    if holiday is not None:
        items.append(holiday)
    items.sort(key=_sort_key)
    return items


def add_countdown(db: Session, user_id: int, payload: dict, now: Optional[datetime] = None) -> dict:
    now = now or now_local()
    count = len(db.scalars(select(CountdownItem.id).where(CountdownItem.user_id == user_id)).all())
    if count >= MAX_ITEMS:
        raise ValueError("最多 %d 条倒计时" % MAX_ITEMS)
    fields = validate_payload(
        payload.get("title"),
        payload.get("kind"),
        payload.get("date"),
        payload.get("day"),
        payload.get("hour"),
        payload.get("minute"),
    )
    row = CountdownItem(user_id=user_id, created_at=now, **fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row, now)


def update_countdown(db: Session, user_id: int, item_id: int, payload: dict, now: Optional[datetime] = None) -> dict:
    now = now or now_local()
    if item_id == HOLIDAY_ITEM_ID:
        raise ValueError("法定假期是自动生成的，不能改")
    row = db.scalar(select(CountdownItem).where(CountdownItem.id == item_id, CountdownItem.user_id == user_id))
    if row is None:
        raise KeyError(item_id)
    fields = validate_payload(
        payload.get("title"),
        payload.get("kind"),
        payload.get("date"),
        payload.get("day"),
        payload.get("hour"),
        payload.get("minute"),
    )
    for key, value in fields.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return _to_out(row, now)


def delete_countdown(db: Session, user_id: int, item_id: int) -> None:
    if item_id == HOLIDAY_ITEM_ID:
        raise ValueError("法定假期是自动生成的，不能删")
    row = db.scalar(select(CountdownItem).where(CountdownItem.id == item_id, CountdownItem.user_id == user_id))
    if row is None:
        raise KeyError(item_id)
    db.delete(row)
    db.commit()
