"""A 股建议：自身均线、相对沪深300，再叠消息倾向和样本内回放。"""

from typing import Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import StockBar, StockQuote
from ..prefs import get_budget
from ..stocks.news import news_context
from ..stocks.universe import (
    active_watchlist,
    lot_cost,
    lot_size,
    meta_of,
    session_label,
    within_budget,
)

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
            return "no_chase", "黄金ETF离开自己的均线偏远，短线不追"
        if z <= -1.0:
            return "watch_buy", "黄金ETF跌离20日均线，等再靠近均线时看"
        if above20:
            return "hold", "黄金ETF沿自己的均线走，方向还顺着"
        return "hold", "黄金ETF在均线附近，方向还不清楚"

    if code in INDEX_LIKE or kind == "index":
        if above20 and trend_up:
            return "watch_buy", "指数站上20日和60日均线，市场趋势还在；等回踩均线再看，不是让你追着打"
        if not above20:
            return "hold", "指数在20日均线下方，市场偏弱，先看成色"
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
        return "hold", "跌在20日均线下方，这只股票趋势偏弱，先不抄"
    return "hold", "没有明显的相对强弱，先观望"


def _apply_news(stance: str, headline: str, news: Optional[Dict]) -> tuple:
    if not news:
        return stance, headline
    lean = news.get("lean") or 0
    label = news.get("label") or ""
    if lean >= 0.25:
        if stance == "hold":
            return "watch_buy", "%s；技术面还中性，消息先给一点关注。" % label
        if stance == "watch_buy":
            return stance, "%s，和技术趋势同向。%s" % (label, headline)
        return stance, "%s，但短线位置仍不适合追。%s" % (label, headline)
    if lean <= -0.25:
        if stance == "watch_buy":
            return "hold", "%s，先把趋势关注降下来。%s" % (label, headline)
        return stance, "%s。%s" % (label, headline)
    return stance, headline


def _median(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _replay_forecast(
    *,
    code: str,
    kind: str,
    bars: List[StockBar],
    bench_bars: Optional[List[StockBar]],
    stance: str,
    price: float,
    atr: float,
    news_lean: float,
) -> Dict:
    horizon = settings.stock_forecast_horizon
    bench = bench_bars or []
    moves: List[float] = []
    start = 24
    last = len(bars) - horizon
    for index in range(start, last):
        window = bars[: index + 1]
        closes = _closes(window)
        if len(closes) < 25:
            continue
        hist_atr = _atr(window)
        if not hist_atr:
            continue
        end_date = window[-1].trade_date
        bench_window = [row for row in bench if row.trade_date <= end_date]
        hist_rel = None
        hist_ret = _period_return(closes, 20)
        bench_ret = _period_return(_closes(bench_window), 20)
        if code not in INDEX_LIKE and code != GOLD_ETF and hist_ret is not None and bench_ret is not None:
            hist_rel = hist_ret - bench_ret
        past, _reason = _stock_stance(
            code=code,
            kind=kind,
            price=closes[-1],
            prev_close=closes[-2] if len(closes) >= 2 else None,
            ma20=sum(closes[-20:]) / 20,
            ma60=sum(closes[-60:]) / len(closes[-60:]) if len(closes) >= 60 else sum(closes) / len(closes),
            atr=hist_atr,
            rel=hist_rel,
            vol_ratio=_vol_ratio(window),
        )
        if past != stance:
            continue
        moves.append(bars[index + horizon].close_price - bars[index].close_price)

    samples = len(moves)
    if stance == "watch_buy":
        wins = sum(1 for move in moves if move > 0)
        fallback = 0.45 * atr
    elif stance == "no_chase":
        wins = sum(1 for move in moves if move <= 0)
        fallback = -0.3 * atr
    else:
        wins = sum(1 for move in moves if abs(move) <= 0.8 * atr)
        fallback = 0.0

    win_rate = round(wins / samples * 100, 1) if samples >= 8 else None
    predicted = _median(moves) if samples >= 8 else fallback
    predicted = (predicted or 0) + news_lean * 0.35 * atr
    return {
        "win_rate": win_rate,
        "win_samples": samples,
        "horizon_days": horizon,
        "predicted_points": _round(predicted),
        "predicted_price": _round(price + predicted),
    }


def evaluate_stock(
    quote: Optional[StockQuote],
    bars: List[StockBar],
    bench_bars: Optional[List[StockBar]] = None,
    news: Optional[Dict] = None,
    budget: Optional[float] = None,
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
    stance, headline = _apply_news(stance, headline, news)
    forecast = _replay_forecast(
        code=code or "",
        kind=kind,
        bars=bars,
        bench_bars=bench_bars,
        stance=stance,
        price=price,
        atr=atr,
        news_lean=(news or {}).get("lean") or 0,
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

    notes = ["现在是 A 股%s。" % session]
    if rel is not None:
        notes.append("近20日这只 %+0.1f%%，沪深300 %+0.1f%%，相对 %+0.1f 个百分点。" % (ret20 or 0, bench_ret or 0, rel))
    if news:
        notes.append("消息倾向 %.2f（%s，%d 条有方向的标题）。这是条件倾向，不是涨跌幅预测。" % (news.get("lean") or 0, news.get("label") or "", news.get("sample") or 0))
    if vol_ratio is not None:
        notes.append("今天成交量是近20日均量的 %.1f 倍。" % vol_ratio)
    if forecast["win_rate"] is not None:
        notes.append(
            "同一信号在这只股票近几个月里出现 %d 次，%d 个交易日后方向命中 %.1f%%；预测点数是这些结果的中位数，再按消息倾向微调。样本内回放，不是实盘胜率。"
            % (forecast["win_samples"], forecast["horizon_days"], forecast["win_rate"])
        )
    else:
        notes.append("同一信号历史样本不足 8 次，点数先按自身波动估，胜率暂不报。")
    cost = lot_cost(price, code or "")
    if kind != "index" and cost is not None:
        notes.append("按一手 %d 股大约 %.0f 元，预算上限 %.0f 元。" % (lot_size(code or ""), cost, budget if budget is not None else settings.stock_budget_yuan))
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
        "news_lean": (news or {}).get("lean"),
        "news_label": (news or {}).get("label"),
        "news": (news or {}).get("items") or [],
        "win_rate": forecast["win_rate"],
        "win_samples": forecast["win_samples"],
        "horizon_days": forecast["horizon_days"],
        "predicted_points": forecast["predicted_points"],
        "predicted_price": forecast["predicted_price"],
        "lot_size": lot_size(code or "") if kind != "index" else None,
        "lot_cost": _round(lot_cost(price, code or ""), 0) if kind != "index" else None,
        "budget": budget if budget is not None else settings.stock_budget_yuan,
        "as_of": quote.collected_at if quote else None,
    }


def summarize_stock(
    quote: Optional[StockQuote],
    bars: List[StockBar],
    bench_bars: Optional[List[StockBar]] = None,
    news: Optional[Dict] = None,
    budget: Optional[float] = None,
) -> Dict:
    detail = evaluate_stock(quote, bars, bench_bars, news, budget)
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
        "news_label": detail.get("news_label"),
        "win_rate": detail.get("win_rate"),
        "predicted_points": detail.get("predicted_points"),
        "lot_cost": detail.get("lot_cost"),
        "as_of": quote.collected_at if quote else None,
        "ready": bool(detail.get("ready")),
    }


def list_stocks(db: Session) -> Dict:
    quotes = {row.code: row for row in db.scalars(select(StockQuote)).all()}
    bench = _bars_of(db, BENCH_CODE)
    budget = get_budget(db)
    items = []
    for code, name, kind in active_watchlist(quotes.values(), budget):
        quote = quotes.get(code)
        bars = _bars_of(db, code)
        if quote:
            items.append(summarize_stock(quote, bars, bench, news_context(db, code), budget))
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
                    "news_label": None,
                    "win_rate": None,
                    "predicted_points": None,
                    "lot_cost": None,
                    "as_of": None,
                    "ready": False,
                }
            )
    return {"session": session_label(), "budget": budget, "items": items}


def stock_detail(db: Session, code: str) -> Dict:
    meta = meta_of(code)
    if not meta:
        return {"ready": False, "message": "不在当前观察池里"}
    quote = db.get(StockQuote, code)
    budget = get_budget(db)
    if not within_budget(quote.price if quote else None, code, meta["kind"], budget):
        return {"ready": False, "message": "一手超过当前预算，先不看"}
    bars = _bars_of(db, code)
    bench = _bars_of(db, BENCH_CODE)
    return {
        "code": code,
        "name": (quote.name if quote else None) or meta["name"],
        "kind": (quote.kind if quote else None) or meta["kind"],
        "quote": summarize_stock(quote, bars, bench, news_context(db, code), budget) if quote else None,
        "bars": [
            {
                "date": row.trade_date,
                "open": row.open_price,
                "high": row.high_price,
                "low": row.low_price,
                "close": row.close_price,
                "volume": row.volume,
            }
            for row in bars[-240:]
        ],
        "session": session_label(),
    }


def build_stock_advice(db: Session, code: str) -> Dict:
    meta = meta_of(code)
    if not meta:
        return {"ready": False, "message": "不在当前观察池里", "code": code}
    quote = db.get(StockQuote, code)
    budget = get_budget(db)
    if not within_budget(quote.price if quote else None, code, meta["kind"], budget):
        return {"ready": False, "message": "一手超过当前预算，先不看", "code": code}
    return evaluate_stock(quote, _bars_of(db, code), _bars_of(db, BENCH_CODE), news_context(db, code), budget)
