"""A 股规则建议：均线位置 + ATR 档，不下单。"""

from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import StockBar, StockQuote
from ..stocks.universe import WATCHLIST, meta_of, session_label

LOW_ZONE = -1.0
HIGH_ZONE = 1.5


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return None if value is None else round(value, digits)


def _bars_of(db: Session, code: str) -> List[StockBar]:
    return db.scalars(select(StockBar).where(StockBar.code == code).order_by(StockBar.trade_date.asc())).all()


def evaluate_stock(quote: Optional[StockQuote], bars: List[StockBar]) -> Dict:
    meta = meta_of(quote.code) if quote else None
    name = (quote.name if quote else None) or (meta or {}).get("name") or ""
    kind = (quote.kind if quote else None) or (meta or {}).get("kind") or "stock"
    price = quote.price if quote else (bars[-1].close_price if bars else None)
    if price is None:
        return {"ready": False, "message": "还没有这只的报价", "code": quote.code if quote else None}

    closes = [row.close_price for row in bars if row.close_price]
    if len(closes) < 25:
        return {
            "ready": False,
            "code": quote.code if quote else None,
            "name": name,
            "kind": kind,
            "price": price,
            "message": "日线不足，先点一次刷新股票数据",
        }

    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / len(closes[-60:]) if len(closes) >= 60 else sum(closes) / len(closes)
    true_ranges = []
    for index in range(1, len(bars)):
        prev = bars[index - 1].close_price
        bar = bars[index]
        if bar.high_price is None or bar.low_price is None or not prev:
            continue
        true_ranges.append(
            max(bar.high_price - bar.low_price, abs(bar.high_price - prev), abs(bar.low_price - prev))
        )
    atr = sum(true_ranges[-14:]) / len(true_ranges[-14:]) if true_ranges else None
    if not atr:
        return {"ready": False, "code": quote.code if quote else None, "name": name, "message": "日线缺少高低价，算不出波动"}

    highs = [row.high_price for row in bars[-20:] if row.high_price is not None]
    lows = [row.low_price for row in bars[-20:] if row.low_price is not None]
    swing_high = max(highs) if highs else None
    swing_low = min(lows) if lows else None
    z = (price - ma20) / atr
    session = session_label()

    if z <= LOW_ZONE:
        stance, headline = "watch_buy", "价格在均线下方一个 ATR 以上，可以关注分批接，不是让你现在市价买满"
    elif z >= HIGH_ZONE:
        stance, headline = "no_chase", "已经高出均线较多，先不追，等回落再看下方档位"
    else:
        stance, headline = "hold", "在均线附近，没有明显位置优势，观望为主"

    def ladder(candidates, below: bool, limit: int = 3) -> List[Dict]:
        kept: List[Dict] = []
        for value, note in candidates:
            if value is None:
                continue
            if below and value >= price:
                continue
            if not below and value < price:
                continue
            if any(abs(value / item["price"] - 1) < 0.005 for item in kept):
                continue
            kept.append(
                {
                    "price": _round(value),
                    "note": note,
                    "gap_pct": _round((value / price - 1) * 100),
                    "kind": "target",
                }
            )
            if len(kept) >= limit:
                break
        kept.sort(key=lambda item: item["price"], reverse=below)
        return kept

    buy_levels = ladder(
        [
            (price - 0.5 * atr, "回落半个 ATR，试探关注"),
            (price - 1.2 * atr, "再跌一个多 ATR，加一档观察"),
            (ma20, "回踩 20 日均线"),
            (swing_low, "近 20 日低点附近，跌破就先放下"),
        ],
        below=True,
    )
    sell_levels = ladder(
        [
            (swing_high, "近 20 日高点，站不上就减观察"),
            (price + 0.6 * atr, "反弹半个多 ATR"),
            (price + 1.5 * atr, "冲高一个半 ATR"),
        ],
        below=False,
    )

    notes = [
        "现在是 A 股%s。" % session,
        "现价相对 20 日均线偏离 %.1f 个 ATR，ATR14 约 %.2f。" % (z, atr),
        "这是按均线和波动算出的参考位，不是投资建议。系统不会下单，也不会连券商。",
    ]
    return {
        "ready": True,
        "code": quote.code,
        "name": name,
        "kind": kind,
        "price": price,
        "prev_close": quote.prev_close if quote else None,
        "change_amt": quote.change_amt if quote else None,
        "change_rate": quote.change_rate if quote else None,
        "stance": stance,
        "headline": headline,
        "z_score": _round(z, 2),
        "ma20": _round(ma20),
        "ma60": _round(ma60),
        "atr": _round(atr),
        "swing_high": _round(swing_high),
        "swing_low": _round(swing_low),
        "buy_levels": buy_levels,
        "sell_levels": sell_levels,
        "session": session,
        "notes": notes,
        "as_of": quote.collected_at if quote else None,
    }


def summarize_stock(quote: Optional[StockQuote], bars: List[StockBar]) -> Dict:
    detail = evaluate_stock(quote, bars)
    meta = meta_of(quote.code) if quote else None
    return {
        "code": quote.code if quote else None,
        "name": quote.name if quote else (meta or {}).get("name"),
        "kind": quote.kind if quote else (meta or {}).get("kind"),
        "price": quote.price if quote else None,
        "prev_close": quote.prev_close if quote else None,
        "change_amt": quote.change_amt if quote else None,
        "change_rate": quote.change_rate if quote else None,
        "high": quote.high_price if quote else None,
        "low": quote.low_price if quote else None,
        "open": quote.open_price if quote else None,
        "stance": detail.get("stance") if detail.get("ready") else None,
        "headline": detail.get("headline") if detail.get("ready") else detail.get("message"),
        "z_score": detail.get("z_score"),
        "as_of": quote.collected_at if quote else None,
        "ready": bool(detail.get("ready")),
    }


def list_stocks(db: Session) -> Dict:
    quotes = {row.code: row for row in db.scalars(select(StockQuote)).all()}
    items = []
    for code, name, kind in WATCHLIST:
        quote = quotes.get(code)
        bars = _bars_of(db, code)
        if quote:
            items.append(summarize_stock(quote, bars))
        else:
            items.append(
                {
                    "code": code,
                    "name": name,
                    "kind": kind,
                    "price": None,
                    "prev_close": None,
                    "change_amt": None,
                    "change_rate": None,
                    "high": None,
                    "low": None,
                    "open": None,
                    "stance": None,
                    "headline": "还没有报价，先刷新一次",
                    "z_score": None,
                    "as_of": None,
                    "ready": False,
                }
            )
    return {"session": session_label(), "items": items}


def stock_detail(db: Session, code: str) -> Dict:
    if not meta_of(code):
        return {"ready": False, "message": "不在当前观察池里"}
    quote = db.get(StockQuote, code)
    bars = _bars_of(db, code)
    return {
        "code": code,
        "name": (quote.name if quote else None) or meta_of(code)["name"],
        "kind": (quote.kind if quote else None) or meta_of(code)["kind"],
        "quote": summarize_stock(quote, bars) if quote else None,
        "bars": [
            {
                "date": row.trade_date,
                "open": row.open_price,
                "high": row.high_price,
                "low": row.low_price,
                "close": row.close_price,
                "volume": row.volume,
            }
            for row in bars[-60:]
        ],
        "session": session_label(),
    }


def build_stock_advice(db: Session, code: str) -> Dict:
    if not meta_of(code):
        return {"ready": False, "message": "不在当前观察池里", "code": code}
    quote = db.get(StockQuote, code)
    return evaluate_stock(quote, _bars_of(db, code))
