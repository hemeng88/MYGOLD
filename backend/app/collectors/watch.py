import logging
from datetime import timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..formula import breakeven_rate, change_rate
from ..models import MarketEvent, PriceTick
from ..timeutil import now_local, to_unix_seconds
from .news import fetch_leading_event
from .sources import Quote

logger = logging.getLogger("mygold.watch")

_persist = {"direction": None, "hits": 0}


def _window_move(db: Session, quote: Quote):
    end_at = quote.source_time or quote.collected_at
    start_at = end_at - timedelta(seconds=settings.move_window_seconds)
    ticks = db.scalars(
        select(PriceTick)
        .where(PriceTick.collected_at >= start_at)
        .order_by(PriceTick.collected_at.asc())
    ).all()
    if len(ticks) < 2:
        return None
    start = ticks[0]
    end_price = quote.price
    rate = change_rate(start.price, end_price)
    return {
        "start_tick": start,
        "start_price": start.price,
        "end_price": end_price,
        "change_amt": round(end_price - start.price, 2),
        "change_rate": rate,
        "window_started_at": start.collected_at,
    }


def _in_cooldown(db: Session, direction: str) -> bool:
    last = db.scalars(
        select(MarketEvent)
        .where(MarketEvent.direction == direction)
        .order_by(MarketEvent.triggered_at.desc())
        .limit(1)
    ).first()
    if not last:
        return False
    delta = now_local() - last.triggered_at
    return delta.total_seconds() < settings.event_cooldown_seconds


async def evaluate_move(db: Session, quote: Quote) -> Optional[MarketEvent]:
    db.flush()
    move = _window_move(db, quote)
    threshold = breakeven_rate()
    if not move or abs(move["change_rate"]) < threshold:
        _persist["direction"] = None
        _persist["hits"] = 0
        return None

    direction = "up" if move["change_rate"] > 0 else "down"
    if _persist["direction"] == direction:
        _persist["hits"] += 1
    else:
        _persist["direction"] = direction
        _persist["hits"] = 1

    if _persist["hits"] < settings.move_persist_checks:
        logger.info(
            "波动持续中 %s %.4f%% hits=%s/%s",
            direction,
            move["change_rate"] * 100,
            _persist["hits"],
            settings.move_persist_checks,
        )
        return None

    if _in_cooldown(db, direction):
        logger.info("同向事件仍在冷却，跳过 %s", direction)
        return None

    news = await fetch_leading_event()
    now = now_local()
    event = MarketEvent(
        trade_date=quote.trade_date,
        triggered_at=now,
        direction=direction,
        start_price=move["start_price"],
        end_price=move["end_price"],
        change_amt=move["change_amt"],
        change_rate=round(move["change_rate"] * 100, 4),
        threshold_rate=round(threshold * 100, 4),
        window_seconds=settings.move_window_seconds,
        window_started_at=move["window_started_at"],
        ts=to_unix_seconds(quote.source_time or now),
        headline=(news or {}).get("headline") or "未检索到明确新闻，已记录超过手续费阈值的持续波动",
        source=(news or {}).get("source") or "monitor",
        url=(news or {}).get("url") or "",
        summary=(news or {}).get("summary") or "",
    )
    db.add(event)
    _persist["hits"] = 0
    logger.info("记录行情事件 %s %s", direction, event.headline[:80])
    return event
