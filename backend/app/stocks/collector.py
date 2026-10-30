"""主板样本落库：日线一天刷一次，现价跟基金持仓股一起在盘中刷。"""

from __future__ import annotations

import json
import logging
import time
from typing import Callable, Dict, List, Optional, Tuple

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
        row.avg3m and row.periods_json
        for row in db.scalars(select(MainboardStock).where(MainboardStock.eligible == 1)).all()
    )


def _load_json(text: Optional[str], default):
    if not text:
        return default
    try:
        return json.loads(text)
    except ValueError:
        return default


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
            row.closes_json = None
            row.periods_json = None
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
        row.closes_json = json.dumps(summary["closes"], separators=(",", ":"))
        row.periods_json = json.dumps(summary["periods"], separators=(",", ":"))
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
    meta.message = "沪深300主板 %d 只有近一年日线，拦截 %d 只，日线失败 %d 只" % (usable, blocked, errors)
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


def normalize_period(period: Optional[str]) -> str:
    return period if period in universe.PERIOD_LABELS else universe.DEFAULT_PERIOD


def _row_period(row: MainboardStock, period: str) -> Optional[Dict]:
    stats = _load_json(row.periods_json, {}).get(period)
    if stats is None and period == "3m" and row.avg3m is not None:
        stats = {"avg": row.avg3m, "bars": row.bars, "start": row.window_start, "end": row.window_end}
    return stats


def _pct(now: Optional[float], base: Optional[float]) -> Optional[float]:
    return universe.vs_avg_pct(now, base)


def _item(row: MainboardStock, period: str) -> Dict:
    stats = _row_period(row, period) or {}
    avg = stats.get("avg")
    return {
        "code": row.code,
        "name": row.name,
        "secid": row.secid,
        "last": row.last,
        "change_pct": row.change_pct,
        "avg3m": row.avg3m,
        "avg": avg,
        "vs_avg_pct": _pct(row.last, avg),
        "period_change_pct": _pct(row.last, stats.get("first")),
        "period_high": stats.get("high"),
        "period_low": stats.get("low"),
        "lot_cost": row.lot_cost,
        "bars": stats.get("bars"),
        "window_start": stats.get("start"),
        "window_end": stats.get("end"),
    }


def list_mainboard(db: Session, period: Optional[str] = None) -> Dict:
    period = normalize_period(period)
    meta = db.get(MainboardMeta, META_ID)
    rows = list(db.scalars(select(MainboardStock)).all())
    usable = [row for row in rows if row.eligible == 1 and row.avg3m is not None]
    items = [_item(row, period) for row in usable]
    items = [item for item in items if item["avg"] is not None]
    items.sort(key=lambda item: (item["vs_avg_pct"] is None, item["vs_avg_pct"] if item["vs_avg_pct"] is not None else 0))
    blocked = [row for row in rows if row.eligible == 0]
    vs_values = [item["vs_avg_pct"] for item in items if item["vs_avg_pct"] is not None]
    below = sum(1 for value in vs_values if value < 0)
    expensive = sum(1 for row in usable if row.lot_cost and row.lot_cost >= 15000)
    as_of = None
    if meta is not None:
        stamps = [stamp for stamp in (meta.quotes_at, meta.klines_at) if stamp]
        as_of = max(stamps) if stamps else None
    # 老库只有三月均价时也判成未就绪，让页面自动补拉一年日线
    ready = bool(items) and has_usable_rows(db)
    return {
        "session": session_label(),
        "ready": ready,
        "period": period,
        "period_label": universe.PERIOD_LABELS[period],
        "periods": [{"value": key, "label": label} for key, label in universe.PERIODS],
        "as_of": as_of,
        "main_est": meta.main_est if meta else 0,
        "cyb": meta.cyb if meta else 0,
        "kcb": meta.kcb if meta else 0,
        "hs300": meta.hs300_count if meta else 0,
        "eligible": meta.eligible_count if meta else 0,
        "blocked": meta.blocked_count if meta else 0,
        "usable": len(items),
        "below": below,
        "mean_vs": round(sum(vs_values) / len(vs_values), 2) if vs_values else None,
        "expensive_lots": expensive,
        "window_start": min((item["window_start"] for item in items if item["window_start"]), default=None),
        "window_end": max((item["window_end"] for item in items if item["window_end"]), default=None),
        "quotes_at": meta.quotes_at if meta else None,
        "klines_at": meta.klines_at if meta else None,
        "items": items,
        "blocked_items": [
            {"code": row.code, "name": row.name, "reason": row.block_reason or row.board}
            for row in sorted(blocked, key=lambda row: (row.block_reason or "", row.code))
        ],
        "message": None
        if ready
        else (meta.message if meta and meta.message else "还没有样本，点刷新拉近一年日线"),
    }


INDEX_TTL_SECONDS = 600
_index_cache: Dict[str, Tuple[float, List[Tuple[str, float]]]] = {}


def _index_bars(symbol: str, loader: Callable[[str], List]) -> List[Tuple[str, float]]:
    """指数日线进程内缓存十分钟：详情是逐只点开的，不能每点一次就打一轮行情源。"""
    cached = _index_cache.get(symbol)
    if cached and time.time() - cached[0] < INDEX_TTL_SECONDS:
        return cached[1]
    try:
        bars = [(day, float(close)) for day, close in loader(symbol)]
    except Exception:
        logger.warning("指数 %s 日线失败", symbol)
        bars = []
    if bars:
        _index_cache[symbol] = (time.time(), bars)
        return bars
    return cached[1] if cached else []


def _with_live_point(bars: List[Tuple[str, float]], trade_date: Optional[str], price: Optional[float]):
    """日线要收盘后才有当天那根，盘中把现价接到末尾，走势才对得上列表里的现价。"""
    if not bars or not trade_date or not price or trade_date <= bars[-1][0]:
        return bars
    return bars + [(trade_date, price)]


def _series_out(window: List[Tuple[str, float]]) -> List[Dict]:
    return [{"d": day, "c": round(close, 3)} for day, close in window]


def mainboard_detail(
    db: Session,
    code: str,
    period: Optional[str] = None,
    index_loader: Callable[[str], List] = universe.fetch_index_closes,
) -> Optional[Dict]:
    period = normalize_period(period)
    row = db.scalars(
        select(MainboardStock).where(MainboardStock.code == code, MainboardStock.eligible == 1)
    ).first()
    if row is None:
        return None
    closes = [(day, float(close)) for day, close in _load_json(row.closes_json, [])]
    bars = _with_live_point(closes, row.trade_date, row.last)
    window = universe.period_window(bars, period)
    start = window[0][0] if window else None

    indexes = []
    for symbol, name in universe.INDEXES:
        index_bars = _index_bars(symbol, index_loader)
        index_window = [item for item in index_bars if start and item[0] >= start]
        indexes.append(
            {
                "symbol": symbol,
                "name": name,
                "last": index_window[-1][1] if index_window else None,
                "change_pct": _pct(index_window[-1][1], index_window[0][1]) if index_window else None,
                "series": _series_out(index_window),
            }
        )

    periods = []
    for key, label in universe.PERIODS:
        stats = universe.period_stats(bars, key)
        periods.append(
            {
                "value": key,
                "label": label,
                "avg": stats["avg"] if stats else None,
                "change_pct": _pct(row.last, stats["first"]) if stats else None,
                "vs_avg_pct": _pct(row.last, stats["avg"]) if stats else None,
            }
        )

    current = universe.period_stats(bars, period) or {}
    return {
        "code": row.code,
        "name": row.name,
        "period": period,
        "period_label": universe.PERIOD_LABELS[period],
        "last": row.last,
        "change_pct": row.change_pct,
        "lot_cost": row.lot_cost,
        "avg": current.get("avg"),
        "high": current.get("high"),
        "low": current.get("low"),
        "vs_avg_pct": _pct(row.last, current.get("avg")),
        "period_change_pct": _pct(row.last, current.get("first")),
        "window_start": current.get("start"),
        "window_end": current.get("end"),
        "series": _series_out(window),
        "indexes": indexes,
        "periods": periods,
    }
