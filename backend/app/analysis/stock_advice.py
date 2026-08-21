"""A 股建议：按股票自己的趋势和相对沪深300的强弱，不套积存金那套。

黄金是单一品种、容易在高位回吐，所以积存金用「偏高就不追」。
茅台、银行、新能源是不同股票，常见看法是站上均线算趋势还在，要比的是大盘而不是金价。
黄金ETF 跟金价走，单独处理。
"""

from typing import Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import StockBar, StockQuote
from ..stocks.universe import WATCHLIST, meta_of, session_label

BENCH_CODE = "sh000300"
GOLD_ETF = "sh518880"
INDEX_LIKE = {"sh000001", "sh000300", "sz399006", "sh510300"}


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return None if value is None else round(value, digits)


def _bars_of(db: Session, code: str) -> List[StockBar]:
    return db.scalars(select(StockBar).where(StockBar.code == code).order_by(StockBar.trade_date.asc())).all()


def _closes(bars: Sequence[StockBar]) -> List[float]:
    return [row.close_price for row in bars if row.close_price]


def _period_return(closes: Sequence[float], days: int = 20) -> Optional[float]:
    if len(closes) < days + 1 or not closes[-1] or not closes[-1 - days]:
        return None
    return (closes[-1] / closes[-1 - days] - 1) * 100


def _atr(bars: Sequence[StockBar]) -> Optional[float]:
    ranges = []
    for index in range(1, len(bars)):
        prev = bars[index - 1].close_price
        bar = bars[index]
        if bar.high_price is None or bar.low_price is None or not prev:
            continue
        ranges.append(max(bar.high_price - bar.low_price, abs(bar.high_price - prev), abs(bar.low_price - prev)))
    if not ranges:
        return None
    window = ranges[-14:]
    return sum(window) / len(window)


def _vol_ratio(bars: Sequence[StockBar]) -> Optional[float]:
    vols = [row.volume for row in bars[-21:] if row.volume]
    if len(vols) < 6:
        return None
    today, rest = vols[-1], vols[:-1]
    avg = sum(rest) / len(rest)
    if not avg:
        return None
    return today / avg


def _limit_pct(code: str) -> float:
    if code.startswith("sz300") or code.startswith("sh688") or code.startswith("sz399"):
        return 0.20
    return 0.10


def _stock_stance(
    *,
    code: str,
    kind: str,
    price: float,
    prev_close: Optional[float],
    ma20: float,
    ma60: float,
    atr: float,
    rel: Optional[float],
    vol_ratio: Optional[float],
) -> tuple:
    z = (price - ma20) / atr
    above20 = price >= ma20
    trend_up = ma20 >= ma60
    day_ret = (price / prev_close - 1) if prev_close else None

    if code == GOLD_ETF:
        if z >= 1.8:
            return "no_chase", "黄金ETF跟金价走，现在离开均线偏远，按品种回撤看，不和茅台银行比"
        if z <= -1.0:
            return "watch_buy", "黄金ETF跌离20日均线，若只是跟着金价回撤，等再靠近均线时看"
        if above20:
            return "hold", "黄金ETF沿自己的均线走，先看金价方向"
        return "hold", "黄金ETF在均线附近，方向还不清楚"

    if code in INDEX_LIKE or kind == "index":
        if above20 and trend_up:
            return "watch_buy", "指数站上20日和60日均线，市场趋势还在；等回踩均线再看，不是让你追着打"
        if not above20:
            return "hold", "指数在20日均线下方，市场偏弱，先看成色，不按黄金超卖去抄"
        return "hold", "指数夹在均线之间，方向还不清楚"

    limit = _limit_pct(code)
    if day_ret is not None and day_ret >= limit * 0.92:
        return "no_chase", "接近涨停，短线拥挤，不追板"
    if day_ret is not None and day_ret <= -limit * 0.92:
        return "hold", "接近跌停，先看住，不抄飞刀"

    if rel is not None and rel >= 2 and above20:
        extra = "，成交也比近20日热" if vol_ratio and vol_ratio >= 1.3 else ""
        return "watch_buy", "近20日强于沪深300约 %.1f 个百分点，且站上均线，趋势还在%s；等回踩20日线再看" % (rel, extra)
    if rel is not None and rel <= -2 and not above20:
        return "hold", "近20日弱于沪深300约 %.1f 个百分点，又在均线下方，先不抄底" % abs(rel)
    if above20 and trend_up:
        return "hold", "自己还在均线上方，但对沪深300没有明显强弱，观望回调"
    if not above20:
        return "hold", "跌在20日均线下方，这只股票趋势偏弱，和黄金跌深了要买不是一回事"
    return "hold", "没有明显的相对强弱，先观望"


def evaluate_stock(
    quote: Optional[StockQuote],
    bars: List[StockBar],
    bench_bars: Optional[List[StockBar]] = None,
) -> Dict:
    meta = meta_of(quote.code) if quote else None
    name = (quote.name if quote else None) or (meta or {}).get("name") or ""
    kind = (quote.kind if quote else None) or (meta or {}).get("kind") or "stock"
    code = quote.code if quote else None
    price = quote.price if quote else (bars[-1].close_price if bars else None)
    if price is None:
        return {"ready": False, "message": "还没有这只的报价", "code": code}

    closes = _closes(bars)
    if len(closes) < 25:
        return {
            "ready": False,
            "code": code,
            "name": name,
            "kind": kind,
            "price": price,
            "message": "日线不足，先点一次刷新股票数据",
        }

    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / len(closes[-60:]) if len(closes) >= 60 else sum(closes) / len(closes)
    atr = _atr(bars)
    if not atr:
        return {"ready": False, "code": code, "name": name, "message": "日线缺少高低价，算不出波动"}

    highs = [row.high_price for row in bars[-20:] if row.high_price is not None]
    lows = [row.low_price for row in bars[-20:] if row.low_price is not None]
    swing_high = max(highs) if highs else None
    swing_low = min(lows) if lows else None
    z = (price - ma20) / atr
    ret20 = _period_return(closes, 20)
    bench_ret = _period_return(_closes(bench_bars or []), 20)
    rel = None
    if code not in INDEX_LIKE and code != GOLD_ETF and ret20 is not None and bench_ret is not None:
        rel = ret20 - bench_ret
    vol_ratio = _vol_ratio(bars)
    session = session_label()
    stance, headline = _stock_stance(
        code=code or "",
        kind=kind,
        price=price,
        prev_close=quote.prev_close if quote else None,
        ma20=ma20,
        ma60=ma60,
        atr=atr,
        rel=rel,
        vol_ratio=vol_ratio,
    )

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
            (ma20, "回踩自己的 20 日均线"),
            (price - 0.6 * atr, "回落大半个自身 ATR"),
            (ma60, "回踩 60 日均线"),
            (swing_low, "近 20 日低点，跌破先放下"),
        ],
        below=True,
    )
    sell_levels = ladder(
        [
            (swing_high, "近 20 日高点"),
            (price + 0.6 * atr, "再走大半个自身 ATR"),
            (ma20 if price < ma20 else None, "反抽 20 日均线"),
        ],
        below=False,
    )

    notes = [
        "现在是 A 股%s。" % session,
        "这是股票自己的趋势和相对强弱，不套积存金「高位不追」那一套；茅台、银行、新能源只跟自己的均线和沪深300比。",
    ]
    if rel is not None:
        notes.append("近20日这只 %+0.1f%%，沪深300 %+0.1f%%，相对 %+0.1f 个百分点。" % (ret20 or 0, bench_ret or 0, rel))
    elif code == GOLD_ETF:
        notes.append("黄金ETF按金价品种看，不参与和沪深300比强弱。")
    elif code in INDEX_LIKE:
        notes.append("指数/宽基ETF只看自身均线趋势，不拿个股超卖逻辑去抄。")
    if vol_ratio is not None:
        notes.append("今天成交量是近20日均量的 %.1f 倍。" % vol_ratio)
    notes.append("规则参考，不是投资建议。系统不会下单，也不会连券商。")

    return {
        "ready": True,
        "code": code,
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
        "vs_index_pct": _round(rel, 2),
        "vol_ratio": _round(vol_ratio, 2),
        "buy_levels": buy_levels,
        "sell_levels": sell_levels,
        "session": session,
        "notes": notes,
        "as_of": quote.collected_at if quote else None,
    }


def summarize_stock(
    quote: Optional[StockQuote],
    bars: List[StockBar],
    bench_bars: Optional[List[StockBar]] = None,
) -> Dict:
    detail = evaluate_stock(quote, bars, bench_bars)
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
        "vs_index_pct": detail.get("vs_index_pct"),
        "as_of": quote.collected_at if quote else None,
        "ready": bool(detail.get("ready")),
    }


def list_stocks(db: Session) -> Dict:
    quotes = {row.code: row for row in db.scalars(select(StockQuote)).all()}
    bench = _bars_of(db, BENCH_CODE)
    items = []
    for code, name, kind in WATCHLIST:
        quote = quotes.get(code)
        bars = _bars_of(db, code)
        if quote:
            items.append(summarize_stock(quote, bars, bench))
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
                    "vs_index_pct": None,
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
    bench = _bars_of(db, BENCH_CODE)
    return {
        "code": code,
        "name": (quote.name if quote else None) or meta_of(code)["name"],
        "kind": (quote.kind if quote else None) or meta_of(code)["kind"],
        "quote": summarize_stock(quote, bars, bench) if quote else None,
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
    return evaluate_stock(quote, _bars_of(db, code), _bars_of(db, BENCH_CODE))
