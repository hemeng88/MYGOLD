"""A 股报价和日线：新浪 hq + 日 K，失败不影响黄金主采集。"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import StockBar, StockQuote
from ..prefs import get_budget
from ..timeutil import now_local
from .news import collect_news
from .universe import active_watchlist, all_codes, meta_of

logger = logging.getLogger("mygold.stocks")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
}
EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
EM_KLINE_LIMIT = 5000
EM_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Referer": "https://quote.eastmoney.com/",
}

_HQ_LINE = re.compile(r'hq_str_([a-z]{2}\d+)="([^"]*)"')


def _num(value) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_quotes() -> List[Dict]:
    url = settings.stock_hq_url + ",".join(all_codes())
    with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
        response = client.get(url, headers=HEADERS)
        response.raise_for_status()
    text = response.content.decode("gbk", errors="ignore")
    now = now_local()
    out: List[Dict] = []
    for match in _HQ_LINE.finditer(text):
        code, payload = match.group(1), match.group(2)
        parts = payload.split(",")
        if len(parts) < 6:
            continue
        meta = meta_of(code)
        price = _num(parts[3])
        prev = _num(parts[2])
        if price is None or price <= 0:
            continue
        change = round(price - prev, 4) if prev else None
        rate = round(change / prev * 100, 3) if change is not None and prev else None
        source_time = None
        if len(parts) >= 32:
            try:
                source_time = datetime.strptime("%s %s" % (parts[30], parts[31].split(".")[0]), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                source_time = None
        out.append(
            {
                "code": code,
                "name": (meta or {}).get("name") or parts[0],
                "kind": (meta or {}).get("kind") or "stock",
                "price": price,
                "prev_close": prev,
                "open_price": _num(parts[1]),
                "high_price": _num(parts[4]),
                "low_price": _num(parts[5]),
                "volume": _num(parts[8]) if len(parts) > 8 else None,
                "amount": _num(parts[9]) if len(parts) > 9 else None,
                "change_amt": change,
                "change_rate": rate,
                "source": "sina_hq",
                "source_time": source_time,
                "collected_at": now,
            }
        )
    return out


def upsert_quotes(db: Session, quotes: List[Dict]) -> int:
    if not quotes:
        return 0
    existing = {
        row.code: row
        for row in db.scalars(select(StockQuote).where(StockQuote.code.in_([item["code"] for item in quotes]))).all()
    }
    written = 0
    for item in quotes:
        row = existing.get(item["code"])
        if row is None:
            row = StockQuote(code=item["code"])
            db.add(row)
        for key, value in item.items():
            setattr(row, key, value)
        written += 1
    db.commit()
    return written


def _secid(code: str) -> str:
    return "%s.%s" % ("1" if code.startswith("sh") else "0", code[2:])


def _parse_sina_bars(rows) -> List[Dict]:
    if not isinstance(rows, list):
        return []
    bars = []
    for row in rows:
        close = _num(row.get("close"))
        day = row.get("day")
        if not day or close is None:
            continue
        bars.append(
            {
                "trade_date": str(day)[:10],
                "open_price": _num(row.get("open")),
                "high_price": _num(row.get("high")),
                "low_price": _num(row.get("low")),
                "close_price": close,
                "volume": _num(row.get("volume")),
            }
        )
    return bars


def _parse_eastmoney_bars(payload) -> List[Dict]:
    klines = ((payload or {}).get("data") or {}).get("klines") or []
    bars = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 6:
            continue
        close = _num(parts[2])
        if not parts[0] or close is None:
            continue
        bars.append(
            {
                "trade_date": parts[0][:10],
                "open_price": _num(parts[1]),
                "high_price": _num(parts[3]),
                "low_price": _num(parts[4]),
                "close_price": close,
                "volume": _num(parts[5]),
            }
        )
    return bars


def _merge_bars(*groups: List[Dict]) -> List[Dict]:
    by_date: Dict[str, Dict] = {}
    for group in groups:
        for bar in group:
            by_date[bar["trade_date"]] = bar
    return [by_date[day] for day in sorted(by_date)]


async def fetch_bars(client: httpx.AsyncClient, code: str) -> List[Dict]:
    sina: List[Dict] = []
    east: List[Dict] = []
    try:
        response = await client.get(
            EM_KLINE_URL,
            params={
                "secid": _secid(code),
                "klt": 101,
                "fqt": 1,
                "lmt": EM_KLINE_LIMIT,
                "end": "20500101",
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57",
            },
            headers=EM_HEADERS,
        )
        response.raise_for_status()
        east = _parse_eastmoney_bars(response.json())
    except Exception:
        logger.exception("东方财富日线失败 %s", code)
    try:
        response = await client.get(
            settings.stock_kline_url,
            params={"symbol": code, "scale": 240, "ma": "no", "datalen": settings.stock_kline_limit},
            headers=HEADERS,
        )
        response.raise_for_status()
        sina = _parse_sina_bars(response.json())
    except Exception:
        logger.exception("新浪日线失败 %s", code)
    return _merge_bars(sina, east)


def upsert_bars(db: Session, code: str, bars: List[Dict]) -> int:
    if not bars:
        return 0
    dates = [bar["trade_date"] for bar in bars]
    existing = {
        row.trade_date: row
        for row in db.scalars(select(StockBar).where(StockBar.code == code, StockBar.trade_date.in_(dates))).all()
    }
    now = now_local()
    written = 0
    for bar in bars:
        row = existing.get(bar["trade_date"])
        if row is None:
            row = StockBar(code=code, trade_date=bar["trade_date"])
            db.add(row)
        row.open_price = bar["open_price"]
        row.high_price = bar["high_price"]
        row.low_price = bar["low_price"]
        row.close_price = bar["close_price"]
        row.volume = bar["volume"]
        row.source = "sina_kline"
        row.updated_at = now
        written += 1
    db.commit()
    return written


def collect_quotes(db: Session) -> Dict:
    quotes = fetch_quotes()
    written = upsert_quotes(db, quotes)
    return {"ok": True, "quotes": written, "message": "A股报价 %d 只" % written}


async def collect_bars(db: Session) -> Dict:
    written = 0
    async with httpx.AsyncClient(timeout=max(settings.request_timeout_seconds, 25), follow_redirects=True) as client:
        for code, _name, _kind in active_watchlist(db.scalars(select(StockQuote)).all(), get_budget(db)):
            try:
                bars = await fetch_bars(client, code)
                written += upsert_bars(db, code, bars)
            except Exception:
                logger.exception("拉 %s 日线失败", code)
                db.rollback()
    return {"ok": True, "bars": written, "message": "A股日线写入 %d 条" % written}


async def refresh_stocks(db: Session, include_bars: bool = False, include_news: bool = True) -> Dict:
    quote_result = collect_quotes(db)
    bar_result = {"bars": 0, "message": ""}
    news_result = {"news": 0, "message": ""}
    if include_bars:
        bar_result = await collect_bars(db)
    if include_news:
        news_result = await collect_news(db)
    return {
        "ok": True,
        "quotes": quote_result["quotes"],
        "bars": bar_result.get("bars") or 0,
        "news": news_result.get("news") or 0,
        "message": "；".join(
            part
            for part in (quote_result["message"], bar_result.get("message"), news_result.get("message"))
            if part
        ),
    }
