"""买卖参考价位。

规则很朴素：用沪金日线算出均线、ATR 和近期高低点，换算到积存金报价上，
再看当前价站在哪个位置，给出分批买入档、卖出档和保本线。
卖出手续费 0.4% 是硬约束——低于保本价卖出必亏，所以任何减仓建议都要先过这道线。
"""

import statistics
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..collectors.history import load_bars
from ..collectors.service import get_latest_quote
from ..config import settings
from ..formula import breakeven_sell_price
from ..holdings import list_holdings
from ..models import DailySummary, NewsFlash
from ..timeutil import now_local

# 位置用 ATR 的倍数衡量：偏离一个 ATR 以上才算真的偏离
LOW_ZONE = -1.0
HIGH_ZONE = 1.5


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return None if value is None else round(value, digits)


def _basis_scale(db: Session, bars: List[Dict], price: float) -> Dict:
    """积存金报价比沪金低一点，用两边收盘价的中位数比例做换算。

    只用当前价除以沪金收盘会把盘中涨跌混进基差里，所以优先取历史重叠日。
    """
    closes = {bar["trade_date"]: bar["close"] for bar in bars}
    rows = db.scalars(
        select(DailySummary).order_by(DailySummary.trade_date.desc()).limit(30)
    ).all()
    ratios = [
        row.close_price / closes[row.trade_date]
        for row in rows
        if row.close_price and closes.get(row.trade_date)
    ]
    if ratios:
        return {"scale": statistics.median(ratios), "sample_days": len(ratios), "source": "重叠交易日"}
    latest_close = bars[-1]["close"] if bars else None
    if latest_close:
        return {"scale": price / latest_close, "sample_days": 0, "source": "当前价比沪金收盘"}
    return {"scale": 1.0, "sample_days": 0, "source": "无可用基差"}


def _recent_drivers(db: Session, days: int = 5) -> List[Dict]:
    since = (now_local().date() - timedelta(days=days)).isoformat()
    rows = db.scalars(select(NewsFlash).where(NewsFlash.session_date >= since)).all()
    scores: Dict[str, float] = defaultdict(float)
    for row in rows:
        for tag in row.tags.split(","):
            if tag:
                scores[tag] += row.weight or 1.0
    total = sum(scores.values())
    if not total:
        return []
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:3]
    return [{"tag": tag, "share_pct": round(score / total * 100, 1)} for tag, score in ranked]


def build_advice(db: Session) -> Dict:
    quote = get_latest_quote(db)
    if not quote:
        return {"ready": False, "message": "还没有采集到价格，先点一次采集"}

    price = float(quote.price)
    today = now_local().date()
    bars = load_bars(db, today - timedelta(days=200), today)
    if len(bars) < 25:
        return {
            "ready": False,
            "message": "历史日线不足，先在归因页点一次更新",
            "price": price,
        }

    basis = _basis_scale(db, bars, price)
    scale = basis["scale"]

    def to_quote(value: Optional[float]) -> Optional[float]:
        return None if value is None else value * scale

    closes = [bar["close"] for bar in bars]
    ma20 = to_quote(sum(closes[-20:]) / 20)
    ma60 = to_quote(sum(closes[-60:]) / len(closes[-60:]))

    true_ranges = []
    for index in range(1, len(bars)):
        prev_close = bars[index - 1]["close"]
        bar = bars[index]
        if bar["high"] is None or bar["low"] is None:
            continue
        true_ranges.append(
            max(bar["high"] - bar["low"], abs(bar["high"] - prev_close), abs(bar["low"] - prev_close))
        )

    atr = to_quote(sum(true_ranges[-14:]) / len(true_ranges[-14:])) if true_ranges else None
    if not atr:
        return {"ready": False, "message": "日线缺少高低价，无法算波动区间", "price": price}

    highs = [bar["high"] for bar in bars[-20:] if bar["high"] is not None]
    lows = [bar["low"] for bar in bars[-20:] if bar["low"] is not None]
    swing_high = to_quote(max(highs)) if highs else None
    swing_low = to_quote(min(lows)) if lows else None

    z = (price - ma20) / atr
    holdings = list_holdings(db)
    breakeven = holdings.breakeven_sell
    has_position = bool(holdings.total_grams)
    in_profit = bool(breakeven and price > breakeven)

    if z <= LOW_ZONE:
        stance = "accumulate"
        headline = "价格低于均线一个波动区间，偏向分批买入"
    elif z >= HIGH_ZONE:
        stance = "reduce" if in_profit else "wait"
        headline = (
            "价格高于均线较多，持仓已过保本线，可考虑分批止盈"
            if in_profit
            else "价格偏高，追买性价比低，等回踩"
        )
    else:
        stance = "hold"
        headline = "价格在均线附近震荡，没有明显边缘，观望或小额定投"

    def ladder(candidates, below: bool, limit: int = 3, bound: Optional[float] = None) -> List[Dict]:
        """挑出方向正确的档位，太靠近的合并掉，只留最有代表性的几档。"""
        edge = price if bound is None else bound
        kept: List[Dict] = []
        for value, note in candidates:
            if value is None:
                continue
            if below and value >= edge:
                continue
            if not below and value < edge:
                continue
            # 相差不到 0.5% 的两档在盘面上没有区别，留先出现的那个
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
            (price - 0.5 * atr, "回落半个 ATR，试探性买"),
            (price - 1.2 * atr, "再跌一个多 ATR，加一档"),
            (ma20, "回踩 20 日均线"),
            (swing_low, "近 20 日低点，跌破就别接了"),
        ],
        below=True,
    )

    # 有持仓时保本线就是硬下限：低于它的价位卖出必亏，不该出现在卖出档里
    floor = breakeven if (has_position and breakeven and breakeven > price) else None
    sell_levels = ladder(
        [
            (floor, "保本线（含 %.1f%% 卖出费），到这儿才不亏" % (settings.sell_fee_rate * 100)),
            (swing_high, "近 20 日高点，站不上就走"),
            (price + 0.6 * atr, "反弹半个多 ATR，减一部分"),
            (price + 1.5 * atr, "冲高一个半 ATR，再减一档"),
            ((floor or price) + 0.8 * atr, "越过保本再涨一段，走一批"),
        ],
        below=False,
        bound=floor,
    )
    if floor and sell_levels:
        sell_levels[0]["kind"] = "breakeven"

    notes = []
    if not has_position:
        notes.append("当前没有持仓记录，卖出档位只是价格参考。")
    elif not in_profit and breakeven:
        notes.append(
            "现价还没到保本线 %.2f，还差 %.2f 元（%.2f%%），这时候卖出是亏的。"
            % (breakeven, breakeven - price, (breakeven / price - 1) * 100)
        )
    elif breakeven:
        notes.append(
            "现价已高于保本线 %.2f，全卖净赚 %.2f 元。"
            % (breakeven, holdings.net_if_sell_now or 0)
        )
    notes.append(
        "价位由沪金日线换算而来，基差取%s，比例 %.4f。" % (basis["source"], scale)
    )
    notes.append("ATR14 为 %.2f 元，代表最近一天的正常波动幅度。" % atr)
    notes.append("这是按规则算出的参考位，不是投资建议。")

    return {
        "ready": True,
        "as_of": quote.collected_at,
        "price": price,
        "trade_date": quote.trade_date,
        "stance": stance,
        "headline": headline,
        "z_score": _round(z),
        "ma20": _round(ma20),
        "ma60": _round(ma60),
        "atr": _round(atr),
        "swing_high": _round(swing_high),
        "swing_low": _round(swing_low),
        "breakeven": _round(breakeven),
        "avg_cost": _round(holdings.avg_cost),
        "total_grams": holdings.total_grams,
        "net_if_sell_now": holdings.net_if_sell_now,
        "buy_levels": buy_levels,
        "sell_levels": sell_levels,
        "drivers": _recent_drivers(db),
        "notes": notes,
    }
