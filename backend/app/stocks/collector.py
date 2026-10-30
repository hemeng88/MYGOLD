"""主板样本落库：日线一天刷一次，现价跟基金持仓股一起在盘中刷。"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..funds.sources import fetch_market_trade_date
from ..market_session import session_label
from ..models import MainboardMeta, MainboardStock
from ..timeutil import now_local
from . import universe

logger = logging.getLogger("mygold.stocks")

META_ID = 1


def _meta(db: Session) -> MainboardMeta:
    row = db.get(MainboardMeta, META_ID)
    if row is None:
        row = MainboardMeta(id=META_ID)
        db.add(row)
        db.flush()
    return row


def has_usable_rows(db: Session) -> bool:
    return any(
        row.avg3m
        for row in db.scalars(select(MainboardStock).where(MainboardStock.eligible == 1)).all()
    )


def collect_universe(
    db: Session,
    *,
    fetch_counts: Callable[[], Dict[str, int]] = universe.fetch_board_counts,
    fetch_hs300: Callable[[], List[Dict]] = universe.fetch_hs300,
    fetch_klines: Callable[[str], List] = universe.fetch_daily_closes,
) -> Dict:
    """重拉沪深300名单和近三个月日线。失败时保留旧样本，不当成空表。"""
    now = now_local()
    trade_date = fetch_market_trade_date()
    counts = fetch_counts()
    stocks = fetch_hs300()
    if not stocks:
        raise RuntimeError("沪深300名单是空的，这一轮不覆盖旧样本")

    existing = {row.secid: row for row in db.scalars(select(MainboardStock)).all()}
    keep = set()
    usable = 0
    eligible = 0
    blocked = 0
    errors = 0
    for item in stocks:
        code = item["code"]
        name = item["name"]
        symbol = item.get("symbol") or universe.sina_symbol(code) or ""
        secid = universe.secid_of(code)
        if not secid or not symbol:
            errors += 1
            continue
        board, can_buy, reason = universe.classify(code, name)
        row = existing.get(secid)
        if row is None:
            row = MainboardStock(secid=secid, code=code, symbol=symbol)
            db.add(row)
        row.code = code
        row.name = name
        row.symbol = symbol
        row.board = board
        row.eligible = 1 if can_buy else 0
        row.block_reason = reason
        keep.add(secid)
        if not can_buy:
            blocked += 1
            row.avg3m = None
            row.vs_avg_pct = None
            row.bars = None
            row.window_start = None
            row.window_end = None
            continue
        eligible += 1
        bars = fetch_klines(symbol)
        summary = universe.summarize_klines(bars, trade_date)
        if summary is None:
            errors += 1
            continue
        row.last = summary["last"] if row.last is None else row.last
        row.avg3m = summary["avg3m"]
        row.vs_avg_pct = universe.vs_avg_pct(row.last, row.avg3m)
        row.bars = summary["bars"]
        row.window_start = summary["window_start"]
        row.window_end = summary["window_end"]
        row.lot_cost = universe.lot_cost(row.last)
        row.kline_at = now
        usable += 1

    for secid, row in existing.items():
        if secid not in keep:
            db.delete(row)

    meta = _meta(db)
    meta.hs_a = counts.get("hs_a") or 0
    meta.sh_a = counts.get("sh_a") or 0
    meta.sz_a = counts.get("sz_a") or 0
    meta.cyb = counts.get("cyb") or 0
    meta.kcb = counts.get("kcb") or 0
    meta.main_est = counts.get("main_est") or 0
    meta.hs300_count = len(stocks)
    meta.eligible_count = eligible
    meta.blocked_count = blocked
    meta.usable_count = usable
    meta.klines_at = now
    meta.message = "沪深300主板 %d 只有完整三月均价，拦截 %d 只，日线失败 %d 只" % (usable, blocked, errors)
    db.commit()
    logger.info("主板样本日线：%s", meta.message)
    return {
        "ok": usable > 0,
        "quotes": 0,
        "klines": usable,
        "hs300": len(stocks),
        "message": meta.message,
    }


def collect_quotes(db: Session, quote_loader=universe.quote_map) -> Dict:
    rows = list(db.scalars(select(MainboardStock).where(MainboardStock.eligible == 1)).all())
    if not rows:
        return {"ok": False, "quotes": 0, "klines": 0, "hs300": 0, "message": "还没有主板样本，先拉一次日线"}
    quotes = quote_loader([row.secid for row in rows])
    now = now_local()
    written = 0
    for row in rows:
        quote = quotes.get(row.secid)
        if not quote or quote.get("price") is None:
            continue
        row.last = quote["price"]
        row.change_pct = quote.get("change_pct")
        row.name = quote.get("name") or row.name
        row.vs_avg_pct = universe.vs_avg_pct(row.last, row.avg3m)
        row.lot_cost = universe.lot_cost(row.last)
        row.trade_date = quote.get("trade_date") or row.trade_date
        row.quote_at = now
        written += 1
    meta = _meta(db)
    meta.quotes_at = now
    meta.usable_count = sum(1 for row in rows if row.avg3m is not None)
    if written:
        meta.message = "现价已更新 %d 只" % written
    db.commit()
    logger.info("主板样本现价：%d / %d", written, len(rows))
    return {
        "ok": written > 0,
        "quotes": written,
        "klines": 0,
        "hs300": meta.hs300_count,
        "message": "现价更新了 %d / %d 只" % (written, len(rows)),
    }


def refresh_mainboard(db: Session, include_klines: bool = False) -> Dict:
    """页面点刷新：没样本或强制时重算均价，然后刷现价。"""
    need_klines = include_klines or not has_usable_rows(db)
    kline_result = {"ok": True, "quotes": 0, "klines": 0, "hs300": 0, "message": ""}
    if need_klines:
        kline_result = collect_universe(db)
    quote_result = collect_quotes(db)
    return {
        "ok": bool(kline_result.get("ok") and quote_result.get("ok")),
        "quotes": quote_result.get("quotes") or 0,
        "klines": kline_result.get("klines") or 0,
        "hs300": kline_result.get("hs300") or quote_result.get("hs300") or 0,
        "message": "；".join(part for part in (kline_result.get("message"), quote_result.get("message")) if part),
    }


def list_mainboard(db: Session) -> Dict:
    meta = db.get(MainboardMeta, META_ID)
    rows = list(db.scalars(select(MainboardStock)).all())
    usable = [row for row in rows if row.eligible == 1 and row.avg3m is not None]
    usable.sort(key=lambda row: (row.vs_avg_pct is None, row.vs_avg_pct if row.vs_avg_pct is not None else 0))
    blocked = [row for row in rows if row.eligible == 0]
    vs_values = [row.vs_avg_pct for row in usable if row.vs_avg_pct is not None]
    below = sum(1 for value in vs_values if value < 0)
    expensive = sum(1 for row in usable if row.lot_cost and row.lot_cost >= 15000)
    as_of = None
    if meta is not None:
        stamps = [stamp for stamp in (meta.quotes_at, meta.klines_at) if stamp]
        as_of = max(stamps) if stamps else None
    ready = bool(usable)
    return {
        "session": session_label(),
        "ready": ready,
        "as_of": as_of,
        "main_est": meta.main_est if meta else 0,
        "cyb": meta.cyb if meta else 0,
        "kcb": meta.kcb if meta else 0,
        "hs300": meta.hs300_count if meta else 0,
        "eligible": meta.eligible_count if meta else 0,
        "blocked": meta.blocked_count if meta else 0,
        "usable": len(usable),
        "below": below,
        "mean_vs": round(sum(vs_values) / len(vs_values), 2) if vs_values else None,
        "expensive_lots": expensive,
        "window_start": min((row.window_start for row in usable if row.window_start), default=None),
        "window_end": max((row.window_end for row in usable if row.window_end), default=None),
        "quotes_at": meta.quotes_at if meta else None,
        "klines_at": meta.klines_at if meta else None,
        "items": [
            {
                "code": row.code,
                "name": row.name,
                "secid": row.secid,
                "last": row.last,
                "change_pct": row.change_pct,
                "avg3m": row.avg3m,
                "vs_avg_pct": row.vs_avg_pct,
                "lot_cost": row.lot_cost,
                "bars": row.bars,
                "window_start": row.window_start,
                "window_end": row.window_end,
            }
            for row in usable
        ],
        "blocked_items": [
            {"code": row.code, "name": row.name, "reason": row.block_reason or row.board}
            for row in sorted(blocked, key=lambda row: (row.block_reason or "", row.code))
        ],
        "message": None
        if ready
        else (meta.message if meta and meta.message else "还没有样本，点刷新拉近三个月日线"),
    }
