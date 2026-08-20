import json
from typing import List, Optional, Tuple

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import CurvePoint, DailySummary, MarketEvent, PriceTick
from ..schemas import CollectResult, CurvePointOut, CurveResponse, DaySummary, LatestQuote, MarketEventOut
from ..timeutil import format_clock, from_unix_seconds, now_local, trade_date_of, trade_date_today
from .sources import Quote, fetch_latest_as_point, fetch_latest_quote, fetch_today_chart
from .watch import evaluate_move


def _quote_to_schema(quote: Quote) -> LatestQuote:
    return LatestQuote(**quote.to_dict())


def _upsert_points(db: Session, trade_date: str, points: List[Tuple[int, float]], source: str) -> int:
    if not points:
        return 0
    existing = {
        row.ts: row
        for row in db.scalars(select(CurvePoint).where(CurvePoint.trade_date == trade_date)).all()
    }
    upserted = 0
    for ts, price in points:
        row = existing.get(ts)
        if row:
            if row.price != price:
                row.price = price
                row.source = source
                upserted += 1
            continue
        db.add(CurvePoint(trade_date=trade_date, ts=ts, price=price, source=source))
        existing[ts] = None  # type: ignore
        upserted += 1
    return upserted


def rebuild_daily_summary(db: Session, trade_date: str) -> Optional[DailySummary]:
    db.flush()
    points = db.scalars(
        select(CurvePoint).where(CurvePoint.trade_date == trade_date).order_by(CurvePoint.ts.asc())
    ).all()
    if not points:
        return None

    prices = [p.price for p in points]
    last_tick = db.scalars(
        select(PriceTick)
        .where(PriceTick.trade_date == trade_date)
        .order_by(PriceTick.collected_at.desc())
    ).first()

    prev_close = last_tick.yesterday_price if last_tick else None
    close_price = prices[-1]
    change_amt = None
    change_rate = None
    if prev_close:
        change_amt = round(close_price - prev_close, 2)
        change_rate = round(change_amt / prev_close * 100, 4)
    elif last_tick and last_tick.change_amt is not None:
        change_amt = last_tick.change_amt

    summary = db.get(DailySummary, trade_date)
    if not summary:
        summary = DailySummary(trade_date=trade_date)
        db.add(summary)

    summary.open_price = prices[0]
    summary.high_price = max(prices)
    summary.low_price = min(prices)
    summary.close_price = close_price
    summary.prev_close = prev_close
    summary.change_amt = change_amt
    summary.change_rate = change_rate
    summary.point_count = len(points)
    summary.first_ts = points[0].ts
    summary.last_ts = points[-1].ts
    summary.updated_at = now_local()
    return summary


def _should_skip_tick(db: Session, quote: Quote) -> bool:
    last = db.scalars(select(PriceTick).order_by(PriceTick.id.desc()).limit(1)).first()
    if not last:
        return False
    same_price = abs(last.price - quote.price) < 0.0001
    same_source_time = last.source_time == quote.source_time
    return same_price and same_source_time


def save_tick(db: Session, quote: Quote) -> Optional[PriceTick]:
    if _should_skip_tick(db, quote):
        return None
    tick = PriceTick(
        collected_at=quote.collected_at,
        source_time=quote.source_time,
        trade_date=quote.trade_date,
        price=quote.price,
        yesterday_price=quote.yesterday_price,
        change_amt=quote.change_amt,
        change_rate=quote.change_rate,
        source=quote.source,
        raw_json=json.dumps(quote.raw, ensure_ascii=False),
    )
    db.add(tick)
    return tick


async def collect_once(db: Session, include_chart: bool = True) -> CollectResult:
    timeout = httpx.Timeout(settings.request_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        quote = await fetch_latest_quote(client)
        chart_points = await fetch_today_chart(client) if include_chart else []

    tick = save_tick(db, quote)
    point = await fetch_latest_as_point(quote)
    upserted = _upsert_points(db, quote.trade_date, [point], quote.source)
    if chart_points:
        # 曲线接口只保证「当天」完整点集，按点时间归属交易日
        by_date = {}
        for ts, price in chart_points:
            day = trade_date_of(from_unix_seconds(ts))
            by_date.setdefault(day, []).append((ts, price))
        for day, pts in by_date.items():
            upserted += _upsert_points(db, day, pts, "goldmonitor")
            rebuild_daily_summary(db, day)
    rebuild_daily_summary(db, quote.trade_date)
    event = await evaluate_move(db, quote)

    db.commit()
    return CollectResult(
        ok=True,
        message="采集完成" if tick else "价格未变化，已同步当日曲线",
        tick=_quote_to_schema(quote),
        curve_points_upserted=upserted,
        event_recorded=event is not None,
    )


def get_latest_quote(db: Session) -> Optional[LatestQuote]:
    tick = db.scalars(select(PriceTick).order_by(PriceTick.id.desc()).limit(1)).first()
    if not tick:
        return None
    return LatestQuote(
        price=tick.price,
        yesterday_price=tick.yesterday_price,
        change_amt=tick.change_amt,
        change_rate=tick.change_rate,
        source_time=tick.source_time,
        collected_at=tick.collected_at,
        source=tick.source,
        trade_date=tick.trade_date,
    )


def summary_to_schema(row: DailySummary) -> DaySummary:
    return DaySummary(
        date=row.trade_date,
        open=row.open_price,
        high=row.high_price,
        low=row.low_price,
        close=row.close_price,
        prev_close=row.prev_close,
        change_amt=row.change_amt,
        change_rate=row.change_rate,
        point_count=row.point_count or 0,
        first_ts=row.first_ts,
        last_ts=row.last_ts,
        updated_at=row.updated_at,
    )


def get_curve(db: Session, trade_date: Optional[str] = None) -> CurveResponse:
    day = trade_date or trade_date_today()
    points = db.scalars(
        select(CurvePoint).where(CurvePoint.trade_date == day).order_by(CurvePoint.ts.asc())
    ).all()
    summary = db.get(DailySummary, day)
    if not summary:
        summary = rebuild_daily_summary(db, day)
        if summary:
            db.commit()
    return CurveResponse(
        date=day,
        summary=summary_to_schema(summary) if summary else None,
        points=[CurvePointOut(t=p.ts, p=p.price, time=format_clock(p.ts)) for p in points],
    )


def list_days(db: Session) -> List[DaySummary]:
    rows = db.scalars(select(DailySummary).order_by(DailySummary.trade_date.desc())).all()
    return [summary_to_schema(row) for row in rows]


def list_events(db: Session, trade_date: Optional[str] = None, limit: int = 50) -> List[MarketEventOut]:
    stmt = select(MarketEvent).order_by(MarketEvent.triggered_at.desc()).limit(limit)
    if trade_date:
        stmt = (
            select(MarketEvent)
            .where(MarketEvent.trade_date == trade_date)
            .order_by(MarketEvent.triggered_at.desc())
            .limit(limit)
        )
    rows = db.scalars(stmt).all()
    return [
        MarketEventOut(
            id=row.id,
            trade_date=row.trade_date,
            triggered_at=row.triggered_at,
            direction=row.direction,
            start_price=row.start_price,
            end_price=row.end_price,
            change_amt=row.change_amt,
            change_rate=row.change_rate,
            threshold_rate=row.threshold_rate,
            window_seconds=row.window_seconds,
            window_started_at=row.window_started_at,
            ts=row.ts,
            headline=row.headline,
            source=row.source,
            url=row.url,
            summary=row.summary,
        )
        for row in rows
    ]
