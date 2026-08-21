"""A 股报价和日线：新浪 hq + 日 K，失败不影响黄金主采集。"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

import httpx
from sqlalchemy import func, select
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
EM_QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
EM_BACKFILL = 500
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


def _pack_quote(
    *,
    code: str,
    name: str,
    kind: str,
    price: Optional[float],
    prev: Optional[float],
    open_price: Optional[float],
    high: Optional[float],
    low: Optional[float],
    volume: Optional[float],
    amount: Optional[float],
    source: str,
    source_time: Optional[datetime],
) -> Optional[Dict]:
    if price is None or price <= 0:
        return None
    change = round(price - prev, 4) if prev else None
    rate = round(change / prev * 100, 3) if change is not None and prev else None
    return {
        "code": code,
        "name": name,
        "kind": kind,
        "price": price,
        "prev_close": prev,
        "open_price": open_price,
        "high_price": high,
        "low_price": low,
        "volume": volume,
        "amount": amount,
        "change_amt": change,
        "change_rate": rate,
        "source": source,
        "source_time": source_time,
        "collected_at": now_local(),
    }


def fetch_quotes_sina() -> List[Dict]:
    url = settings.stock_hq_url + ",".join(all_codes())
    with httpx.Client(timeout=8, follow_redirects=True) as client:
        response = client.get(url, headers=HEADERS)
        response.raise_for_status()
    text = response.content.decode("gbk", errors="ignore")
    out: List[Dict] = []
    for match in _HQ_LINE.finditer(text):
        code, payload = match.group(1), match.group(2)
        parts = payload.split(",")
        if len(parts) < 6:
            continue
        meta = meta_of(code)
        source_time = None
        if len(parts) >= 32:
            try:
                source_time = datetime.strptime("%s %s" % (parts[30], parts[31].split(".")[0]), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                source_time = None
        item = _pack_quote(
            code=code,
            name=(meta or {}).get("name") or parts[0],
            kind=(meta or {}).get("kind") or "stock",
            price=_num(parts[3]),
            prev=_num(parts[2]),
            open_price=_num(parts[1]),
            high=_num(parts[4]),
            low=_num(parts[5]),
            volume=_num(parts[8]) if len(parts) > 8 else None,
            amount=_num(parts[9]) if len(parts) > 9 else None,
            source="sina_hq",
            source_time=source_time,
        )
        if item:
            out.append(item)
    return out


def fetch_quotes_eastmoney() -> List[Dict]:
    secids = ",".join(_secid(code) for code in all_codes())
    with httpx.Client(timeout=8, follow_redirects=True) as client:
        response = client.get(
            EM_QUOTE_URL,
            params={
                "fltt": 2,
                "invt": 2,
                "fields": "f2,f3,f4,f12,f13,f14,f15,f16,f17,f18,f6,f5",
                "secids": secids,
            },
            headers=EM_HEADERS,
        )
        response.raise_for_status()
    rows = (((response.json() or {}).get("data") or {}).get("diff")) or []
    out: List[Dict] = []
    for row in rows:
        number = str(row.get("f12") or "")
        market = str(row.get("f13") or "")
        prefix = "sh" if market == "1" else "sz"
        code = prefix + number
        meta = meta_of(code)
        if not meta:
            continue
        item = _pack_quote(
            code=code,
            name=meta["name"],
            kind=meta["kind"],
            price=_num(row.get("f2")),
            prev=_num(row.get("f18")),
            open_price=_num(row.get("f17")),
            high=_num(row.get("f15")),
            low=_num(row.get("f16")),
            volume=_num(row.get("f5")),
            amount=_num(row.get("f6")),
            source="em_hq",
            source_time=now_local(),
        )
        if item:
            out.append(item)
    return out


def fetch_quotes() -> List[Dict]:
    try:
        quotes = fetch_quotes_sina()
        if quotes:
            return quotes
    except Exception:
        logger.exception("新浪报价失败，改走东方财富")
    return fetch_quotes_eastmoney()


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


async def _fetch_eastmoney_bars(client: httpx.AsyncClient, code: str, limit: int) -> List[Dict]:
    response = await client.get(
        EM_KLINE_URL,
        params={
            "secid": _secid(code),
            "klt": 101,
            "fqt": 1,
            "lmt": limit,
            "end": "20500101",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
        },
        headers=EM_HEADERS,
    )
    response.raise_for_status()
    return _parse_eastmoney_bars(response.json())


async def _fetch_sina_bars(client: httpx.AsyncClient, code: str, limit: int) -> List[Dict]:
    response = await client.get(
        settings.stock_kline_url,
        params={"symbol": code, "scale": 240, "ma": "no", "datalen": limit},
        headers=HEADERS,
    )
    response.raise_for_status()
    return _parse_sina_bars(response.json())


async def fetch_bars(client: httpx.AsyncClient, code: str, backfill: bool) -> List[Dict]:
    if backfill:
        try:
            east = await _fetch_eastmoney_bars(client, code, EM_BACKFILL)
            if east:
                return east
        except Exception:
            logger.exception("东方财富日线失败 %s", code)
        try:
            return await _fetch_sina_bars(client, code, 240)
        except Exception:
            logger.exception("新浪日线失败 %s", code)
            return []
    try:
        return await _fetch_sina_bars(client, code, 80)
    except Exception:
        logger.exception("新浪日线增量失败 %s", code)
        try:
            return await _fetch_eastmoney_bars(client, code, 80)
        except Exception:
            logger.exception("东方财富日线增量失败 %s", code)
            return []


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


def _bar_count(db: Session, code: str) -> int:
    return db.scalar(select(func.count()).select_from(StockBar).where(StockBar.code == code)) or 0


async def collect_bars(db: Session) -> Dict:
    written = 0
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        for code, _name, _kind in active_watchlist(db.scalars(select(StockQuote)).all(), get_budget(db)):
            try:
                bars = await fetch_bars(client, code, backfill=_bar_count(db, code) < 180)
                written += upsert_bars(db, code, bars)
            except Exception:
                logger.exception("拉 %s 日线失败", code)
                db.rollback()
    return {"ok": True, "bars": written, "message": "A股日线写入 %d 条" % written}


def collect_quotes(db: Session) -> Dict:
    quotes = fetch_quotes()
    written = upsert_quotes(db, quotes)
    return {"ok": True, "quotes": written, "message": "A股报价 %d 只" % written}


async def refresh_stocks(db: Session, include_bars: bool = False, include_news: bool = True) -> Dict:
    quote_result = {"quotes": 0, "message": "报价未取到"}
    bar_result = {"bars": 0, "message": ""}
    news_result = {"news": 0, "message": ""}
    try:
        quote_result = collect_quotes(db)
    except Exception as exc:
        logger.exception("A股报价失败")
        db.rollback()
        quote_result = {"quotes": 0, "message": "报价失败：%s" % exc}
    if include_bars:
        try:
            bar_result = await collect_bars(db)
        except Exception as exc:
            logger.exception("A股日线失败")
            db.rollback()
            bar_result = {"bars": 0, "message": "日线失败：%s" % exc}
    if include_news:
        try:
            news_result = await collect_news(db)
        except Exception as exc:
            logger.exception("股票资讯失败")
            db.rollback()
            news_result = {"news": 0, "message": "资讯失败：%s" % exc}
    return {
        "ok": bool(quote_result.get("quotes")),
        "quotes": quote_result.get("quotes") or 0,
        "bars": bar_result.get("bars") or 0,
        "news": news_result.get("news") or 0,
        "message": "；".join(
            part
            for part in (quote_result.get("message"), bar_result.get("message"), news_result.get("message"))
            if part
        ),
    }
