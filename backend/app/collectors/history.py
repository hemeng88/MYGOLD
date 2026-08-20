"""代理标的历史日线采集：沪金连续 AU0（新浪 JSONP）。

浙商积存金接口只给当天曲线，做半年以上的事件归因必须借一条长历史。
沪金连续和积存金的日内方向基本一致，所以用它当代理标的。
"""

import json
import logging
import re
from datetime import date, timedelta
from typing import Dict, List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import DailyBar
from ..timeutil import now_local

logger = logging.getLogger("mygold.history")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
}

_JSONP = re.compile(rb"\((\[.*\])\)", re.S)


def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def fetch_proxy_daily(client: httpx.AsyncClient) -> List[Dict]:
    response = await client.get(settings.proxy_daily_url, headers=HEADERS)
    response.raise_for_status()
    match = _JSONP.search(response.content)
    if not match:
        raise ValueError("历史日线接口返回格式异常")
    rows = json.loads(match.group(1))
    bars = []
    for row in rows:
        close = _to_float(row.get("c"))
        if not row.get("d") or close is None:
            continue
        bars.append(
            {
                "trade_date": row["d"],
                "open": _to_float(row.get("o")),
                "high": _to_float(row.get("h")),
                "low": _to_float(row.get("l")),
                "close": close,
            }
        )
    return bars


def upsert_bars(db: Session, bars: List[Dict], source: str = "sina") -> int:
    if not bars:
        return 0
    symbol = settings.proxy_symbol
    dates = [bar["trade_date"] for bar in bars]
    existing = {
        row.trade_date: row
        for row in db.scalars(
            select(DailyBar).where(DailyBar.symbol == symbol, DailyBar.trade_date.in_(dates))
        ).all()
    }
    now = now_local()
    written = 0
    for bar in bars:
        row = existing.get(bar["trade_date"])
        if row is None:
            db.add(
                DailyBar(
                    symbol=symbol,
                    trade_date=bar["trade_date"],
                    open_price=bar["open"],
                    high_price=bar["high"],
                    low_price=bar["low"],
                    close_price=bar["close"],
                    source=source,
                    updated_at=now,
                )
            )
            written += 1
            continue
        if row.close_price != bar["close"] or row.high_price != bar["high"]:
            row.open_price = bar["open"]
            row.high_price = bar["high"]
            row.low_price = bar["low"]
            row.close_price = bar["close"]
            row.updated_at = now
            written += 1
    db.commit()
    return written


async def sync_history(db: Session, days: Optional[int] = None) -> int:
    """拉取并写入历史日线，返回新增或更新的条数。"""
    window = days or settings.attribution_window_days
    # 多留一段缓冲，保证窗口首日也能算出涨跌幅
    since = (now_local().date() - timedelta(days=window + 20)).isoformat()
    timeout = httpx.Timeout(max(settings.request_timeout_seconds, 20.0))
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        bars = await fetch_proxy_daily(client)
    bars = [bar for bar in bars if bar["trade_date"] >= since]
    written = upsert_bars(db, bars)
    logger.info("历史日线同步 %s 条（窗口起点 %s）", written, since)
    return written


def load_bars(db: Session, start: date, end: date) -> List[Dict]:
    """取出区间日线，并补上前一交易日涨跌幅。"""
    rows = db.scalars(
        select(DailyBar)
        .where(
            DailyBar.symbol == settings.proxy_symbol,
            DailyBar.trade_date >= start.isoformat(),
            DailyBar.trade_date <= end.isoformat(),
        )
        .order_by(DailyBar.trade_date.asc())
    ).all()
    bars: List[Dict] = []
    for index, row in enumerate(rows):
        prev_close = rows[index - 1].close_price if index else None
        change_pct = None
        if prev_close:
            change_pct = round((row.close_price / prev_close - 1) * 100, 3)
        bars.append(
            {
                "trade_date": row.trade_date,
                "open": row.open_price,
                "high": row.high_price,
                "low": row.low_price,
                "close": row.close_price,
                "prev_close": prev_close,
                "change_pct": change_pct,
            }
        )
    return bars
