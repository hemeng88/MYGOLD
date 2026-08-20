"""财经快讯归档：华尔街见闻 7x24。

两条通道分工不同：
- 日历通道（黄金频道）主要是各国经济数据，覆盖每一天，用来抓通胀、就业、原油库存这类定期公布；
- 叙事通道（全球快讯）量大，只在显著波动日的窗口内抓，用来抓地缘、政策这类突发。
只有能打上标签的条目才入库。
"""

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Optional, Set

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import NewsFlash
from ..timeutil import from_unix_seconds, now_local, to_unix_seconds
from .news import classify_macro_tags

logger = logging.getLogger("mygold.flashes")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://wallstreetcn.com/",
}

CALENDAR = "calendar"
NARRATIVE = "narrative"


def session_date_of(moment: datetime) -> str:
    """收盘后的消息影响下一个交易日，所以按 18:00 切分归属。"""
    if moment.hour >= settings.session_cutoff_hour:
        return (moment.date() + timedelta(days=1)).isoformat()
    return moment.date().isoformat()


async def _fetch_page(client: httpx.AsyncClient, channel: str, cursor: Optional[int]) -> Dict:
    params = {"channel": channel, "limit": settings.flash_page_size}
    if cursor:
        params["cursor"] = cursor
    response = await client.get(settings.flash_api_url, params=params, headers=HEADERS)
    response.raise_for_status()
    return (response.json().get("data") or {})


def _normalize(item: Dict, channel: str, kind: str) -> Optional[Dict]:
    ts = int(item.get("display_time") or 0)
    if not ts:
        return None
    text = "%s %s" % (item.get("title") or "", item.get("content_text") or "")
    tags = classify_macro_tags(text)
    if not tags:
        return None
    published_at = from_unix_seconds(ts)
    # 日历条目自带重要度，叙事条目统一给一个略高于普通数据的权重
    weight = float(item.get("score") or 1) if kind == CALENDAR else 1.2
    return {
        "external_id": str(item.get("id")),
        "published_at": published_at,
        "session_date": session_date_of(published_at),
        "channel": channel,
        "title": (item.get("title") or item.get("content_text") or "").strip()[:300],
        "tags": ",".join(tags),
        "weight": weight,
        "url": (item.get("uri") or "")[:500],
        "ts": ts,
    }


def _store(db: Session, rows: Iterable[Dict], source: str) -> int:
    rows = list(rows)
    if not rows:
        return 0
    ids = [row["external_id"] for row in rows]
    known: Set[str] = set(
        db.scalars(
            select(NewsFlash.external_id).where(
                NewsFlash.source == source, NewsFlash.external_id.in_(ids)
            )
        ).all()
    )
    added = 0
    for row in rows:
        if row["external_id"] in known:
            continue
        known.add(row["external_id"])
        db.add(
            NewsFlash(
                source=source,
                external_id=row["external_id"],
                published_at=row["published_at"],
                session_date=row["session_date"],
                channel=row["channel"],
                title=row["title"],
                tags=row["tags"],
                weight=row["weight"],
                url=row["url"],
            )
        )
        added += 1
    db.commit()
    return added


async def sync_calendar(db: Session, since: date, max_pages: Optional[int] = None) -> int:
    """按游标向前翻日历通道，直到翻过 since。"""
    channel = settings.flash_calendar_channel
    limit_pages = max_pages or settings.flash_max_pages
    timeout = httpx.Timeout(max(settings.request_timeout_seconds, 20.0))
    collected: List[Dict] = []
    cursor: Optional[int] = None
    pages = 0
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        while pages < limit_pages:
            data = await _fetch_page(client, channel, cursor)
            items = data.get("items") or []
            pages += 1
            if not items:
                break
            reached = False
            for item in items:
                row = _normalize(item, channel, CALENDAR)
                if row is None:
                    ts = int(item.get("display_time") or 0)
                    if ts and from_unix_seconds(ts).date() < since:
                        reached = True
                    continue
                if row["published_at"].date() < since:
                    reached = True
                    continue
                collected.append(row)
            cursor = data.get("next_cursor")
            if reached or not cursor:
                break
            await asyncio.sleep(0.08)
    added = _store(db, collected, source="wscn")
    logger.info("日历快讯归档 %s 条（翻页 %s，起点 %s）", added, pages, since)
    return added


async def sync_narrative_window(db: Session, day: str) -> int:
    """抓某个交易日的叙事窗口：前一日 16:00 到当日 18:00。"""
    target = date.fromisoformat(day)
    end = datetime.combine(target, time(settings.session_cutoff_hour, 0))
    start = datetime.combine(target - timedelta(days=1), time(16, 0))
    end_ts = to_unix_seconds(end)
    start_ts = to_unix_seconds(start)
    channel = settings.flash_narrative_channel
    timeout = httpx.Timeout(max(settings.request_timeout_seconds, 20.0))
    collected: List[Dict] = []
    cursor: Optional[int] = min(end_ts, to_unix_seconds(now_local()))
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for _ in range(6):
            data = await _fetch_page(client, channel, cursor)
            items = data.get("items") or []
            if not items:
                break
            oldest = min(int(item.get("display_time") or 0) for item in items)
            for item in items:
                ts = int(item.get("display_time") or 0)
                if ts < start_ts or ts > end_ts:
                    continue
                row = _normalize(item, channel, NARRATIVE)
                if row:
                    collected.append(row)
            cursor = data.get("next_cursor") or oldest
            if oldest < start_ts or not cursor:
                break
            await asyncio.sleep(0.08)
    return _store(db, collected, source="wscn")


async def sync_narrative_days(db: Session, days: Iterable[str]) -> int:
    """给一批交易日补叙事快讯，跳过已经抓过的日子。"""
    total = 0
    for day in days:
        done = db.scalar(
            select(NewsFlash.id)
            .where(
                NewsFlash.session_date == day,
                NewsFlash.channel == settings.flash_narrative_channel,
            )
            .limit(1)
        )
        if done:
            continue
        try:
            total += await sync_narrative_window(db, day)
        except Exception:
            logger.exception("叙事快讯抓取失败：%s", day)
            db.rollback()
    return total


def retag_flashes(db: Session) -> int:
    """分类规则改动后，就地重算已归档快讯的标签，标不上的直接删掉。"""
    rows = list(db.scalars(select(NewsFlash)).all())
    changed = 0
    for row in rows:
        tags = classify_macro_tags(row.title)
        if not tags:
            db.delete(row)
            changed += 1
            continue
        joined = ",".join(tags)
        if joined != row.tags:
            row.tags = joined
            changed += 1
    if changed:
        db.commit()
        logger.info("重打标签，调整 %s 条（共 %s 条）", changed, len(rows))
    return changed


def load_flashes(db: Session, since: date) -> List[NewsFlash]:
    return list(
        db.scalars(
            select(NewsFlash)
            .where(NewsFlash.session_date >= since.isoformat())
            .order_by(NewsFlash.published_at.asc())
        ).all()
    )
