"""买卖参考价位。

规则很朴素：用沪金日线算出均线、ATR 和近期高低点，换算到积存金报价上，
再看当前价站在哪个位置，叠近两日涨跌和交易所开盘时段，给出分批买入档、卖出档和保本线。
卖出手续费 0.4% 是硬约束——低于保本价卖出必亏，所以任何减仓建议都要先过这道线。
高位连涨时禁止追买；时段样本不够 20 天就改用近几日这个钟点的实际流向，不当长期胜率。
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
from .regime import MIN_ZONE_DAYS, measure
from .sessions import snapshot as session_snapshot

# 位置用 ATR 的倍数衡量：偏离一个 ATR 以上才算真的偏离
LOW_ZONE = -1.0
HIGH_ZONE = 1.5

# 表态门槛。原来是 0.10，把消息采集补全之后那一档已经没有优势了，
# 收窄到 0.15：宁可多说几次「看不出优势」，也别拿噪音当方向。
DIRECTION_EDGE = 0.15


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


def _recent_tape(db: Session, price: float) -> Optional[Dict]:
    """积存金最近两个交易日的涨跌，今天用现价相对昨收重算。"""
    rows = db.scalars(select(DailySummary).order_by(DailySummary.trade_date.desc()).limit(4)).all()
    if len(rows) < 2:
        return None
    ordered = list(reversed(rows[:3]))
    changes = []
    for row in ordered:
        pct = row.change_rate
        if pct is None and row.close_price and row.prev_close:
            pct = (row.close_price / row.prev_close - 1) * 100
        if pct is None:
            continue
        changes.append({"date": row.trade_date, "pct": float(pct)})
    if changes and rows[0].prev_close:
        changes[-1] = {
            "date": rows[0].trade_date,
            "pct": (price / rows[0].prev_close - 1) * 100,
        }
    last2 = changes[-2:]
    if len(last2) < 2:
        return None
    return {
        "days": 2,
        "changes": last2,
        "sum_pct": sum(item["pct"] for item in last2),
        "up_days": sum(1 for item in last2 if item["pct"] > 0),
        "down_days": sum(1 for item in last2 if item["pct"] < 0),
    }


def _factor(name: str, label: str, detail: str, stats: Optional[Dict], kind: str = "hist") -> Optional[Dict]:
    """把一个分区的历史胜率折成 [-1, 1] 的分数，样本越薄权重压得越低。"""
    if not stats:
        return None
    days = stats["days"]
    raw = (stats["win_rate"] - 50) / 50
    shrink = days / (days + 20)
    return {
        "name": name,
        "label": label,
        "detail": detail,
        "score": round(raw * shrink, 3),
        "win_rate": stats["win_rate"],
        "mean_next": stats["mean_next"],
        "days": days,
        "kind": kind,
    }


def _session_factor(session: Optional[Dict]) -> Optional[Dict]:
    """当前钟点的金价方向：样本够就用历史胜率，不够就用近几日这个钟点的实际流向。"""
    if not session:
        return None
    samples = session.get("hour_samples") or 0
    win_rate = session.get("hour_win_rate")
    mean_pct = session.get("hour_mean_pct")
    if samples >= MIN_ZONE_DAYS and win_rate is not None and mean_pct is not None:
        return _factor(
            "session",
            "交易时段",
            "现在是%s，这个钟点历史上金价上涨 %d%%"
            % (session.get("band_label") or "未知时段", win_rate),
            {"days": samples, "win_rate": win_rate, "mean_next": mean_pct},
        )
    days = session.get("profile_days") or 0
    if days < 1 or mean_pct is None or samples < 1:
        return None
    shrink = samples / (samples + 8)
    score = max(-1.0, min(1.0, mean_pct / 0.35)) * shrink * 0.65
    hots = [
        item["name"]
        for item in session.get("exchanges") or []
        if item.get("hot") and item.get("open")
    ]
    if hots:
        score *= 1.2
    score = max(-0.22, min(0.22, score))
    who = "；影响较大的%s也在开" % "、".join(hots[:2]) if hots else ""
    return {
        "name": "session",
        "label": "交易时段",
        "detail": "近%d日这个钟点金价平均 %+.2f%%（%d 个观测）%s"
        % (days, mean_pct, samples, who),
        "score": round(score, 3),
        "win_rate": win_rate,
        "mean_next": mean_pct,
        "days": samples,
        "kind": "recent",
    }


def _stretch_factor(z: float, tape: Optional[Dict]) -> Optional[Dict]:
    """高位连涨不追。8/19 之后又走出两根阳线，位置因子却因样本不足被跳过。"""
    if not tape:
        return None
    run = tape["sum_pct"]
    labels = "、".join("%s %+.2f%%" % (item["date"][5:], item["pct"]) for item in tape["changes"])
    if z >= 1.5 and run > 0:
        mag = min(0.45, 0.12 * z + 0.08 * min(run, 2.5))
        return {
            "name": "stretch",
            "label": "近两日位置",
            "detail": "近两日 %s，现价已高出均线 %.1f 个 ATR，连涨后不追" % (labels, z),
            "score": round(-mag, 3),
            "win_rate": None,
            "mean_next": round(run, 2),
            "days": tape["days"],
            "kind": "recent",
        }
    if z <= -1.2 and run < 0:
        mag = min(0.28, 0.08 * abs(z) + 0.05 * min(abs(run), 2.5))
        return {
            "name": "stretch",
            "label": "近两日位置",
            "detail": "近两日 %s，现价低于均线 %.1f 个 ATR" % (labels, abs(z)),
            "score": round(mag, 3),
            "win_rate": None,
            "mean_next": round(run, 2),
            "days": tape["days"],
            "kind": "recent",
        }
    return None


def _hot_open_names(session: Optional[Dict]) -> List[str]:
    if not session:
        return []
    return [
        item["name"]
        for item in session.get("exchanges") or []
        if item.get("hot") and item.get("open")
    ]


def _vol_boost(session: Optional[Dict]) -> float:
    """近两日波动大的钟点、高影响交易所开盘时，把买卖档拉开一点。"""
    boost = 1.0
    if not session:
        return boost
    rank = session.get("hour_vol_rank_pct")
    if rank is not None and rank >= 70:
        boost += 0.15
    if _hot_open_names(session):
        boost += 0.1
    return boost


def _direction_score(
    z: float,
    regime: Optional[Dict],
    session: Optional[Dict] = None,
    tape: Optional[Dict] = None,
) -> Dict:
    """位置、事件、近两日路径、交易时段。历史胜率不够的分区不进分。"""
    if z <= -1.0:
        zone, zone_label = "low", "低于均线一个 ATR 以上"
    elif z >= 1.5:
        zone, zone_label = "high", "高于均线 1.5 个 ATR 以上"
    else:
        zone, zone_label = "mid", "在均线附近"

    candidates: List = []
    if regime and regime.get("ready"):
        candidates.append(
            (
                "价格位置",
                _factor("position", "价格位置", zone_label, regime["position_zones"].get(zone)),
            )
        )
        candidates.append(
            (
                "事件方向",
                _factor(
                    "events",
                    "事件方向",
                    "最近两个交易日的新闻%s（升级分 %+.2f）"
                    % (regime["mood_label"], regime["polarity"]),
                    regime["polarity_zones"].get(regime["mood"]),
                ),
            )
        )
    candidates.append(("近两日位置", _stretch_factor(z, tape)))
    candidates.append(("交易时段", _session_factor(session)))
    skipped = [name for name, item in candidates if not item]
    factors = [item for _, item in candidates if item]
    if not factors:
        return {"score": 0.0, "factors": [], "skipped": skipped}
    return {
        "score": round(sum(item["score"] for item in factors) / len(factors), 3),
        "factors": factors,
        "skipped": skipped,
    }


def evaluate(
    price: float,
    bars: List[Dict],
    basis: Dict,
    position: Dict,
    regime: Optional[Dict] = None,
    session: Optional[Dict] = None,
    tape: Optional[Dict] = None,
) -> Dict:
    """给定价格、日线、持仓和事件环境算出档位。不碰数据库，方便回算历史某一天。"""
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
    breakeven = position.get("breakeven")
    has_position = bool(position.get("total_grams"))
    in_profit = bool(breakeven and price > breakeven)

    direction = _direction_score(z, regime, session=session, tape=tape)
    score = direction["score"]
    high_side = z >= HIGH_ZONE
    stretched_run = bool(high_side and tape and tape.get("sum_pct", 0) > 0.4 and tape.get("up_days", 0) >= 2)

    if not direction["factors"]:
        stance = "hold"
        headline = "历史样本不够，看不出方向优势，下面只给价位参考"
    elif score >= DIRECTION_EDGE:
        stance = "accumulate"
        headline = (
            "位置偏高，但事件环境站在多头一侧，可以顺势买，别一次买满"
            if high_side
            else "位置和事件都偏向多头，适合分批买入"
        )
    elif score > -DIRECTION_EDGE:
        stance = "hold"
        headline = (
            "近两日已经在均线上方连涨，先观望，真想买就挂在下面第一档"
            if stretched_run
            else "优势不明显，观望；真想买就挂在下面第一档等回落"
        )
    else:
        stance = "reduce" if in_profit else "wait"
        headline = (
            "环境转差且持仓已过保本线，可以分批减一些"
            if in_profit
            else "环境偏差，别加仓；现价卖出还不够保本，先等"
        )
    if stance == "accumulate" and stretched_run:
        stance = "hold"
        headline = "事件仍偏多，但近两日已在高位连涨，不追，等回落再看买入档"
    # 数据不支持「偏高就该等回踩」，但价格离均线多远总该讲清楚
    notes_extra = (
        "价格已高于均线 %.1f 个 ATR，买入档都设在现价下方，等回落再接。" % z
        if high_side
        else None
    )

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

    step = atr * _vol_boost(session)
    buy_levels = ladder(
        [
            (price - 0.5 * step, "回落半个 ATR，试探性买"),
            (price - 1.2 * step, "再跌一个多 ATR，加一档"),
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
            (price + 0.6 * step, "反弹半个多 ATR，减一部分"),
            (price + 1.5 * step, "冲高一个半 ATR，再减一档"),
            ((floor or price) + 0.8 * step, "越过保本再涨一段，走一批"),
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
            % (breakeven, position.get("net_if_sell_now") or 0)
        )
    if notes_extra:
        notes.append(notes_extra)
    hist_skipped = [name for name in direction.get("skipped") or [] if name in ("价格位置", "事件方向")]
    if hist_skipped:
        notes.append(
            "%s这个因子今天不参与打分：所处分区历史样本不足 %d 天，胜率算不准。"
            % ("、".join(hist_skipped), MIN_ZONE_DAYS)
        )
    if session:
        names = session.get("open_names") or []
        if names:
            notes.append(
                "此刻东八区 %s，%s开着：%s。"
                % (session.get("clock", ""), session.get("band_label", "空窗"), "、".join(names[:6]))
            )
        elif session.get("band_label"):
            notes.append("此刻东八区 %s，主要股票市场都还没开。" % session.get("clock", ""))
        if any(item.get("name") == "session" and item.get("kind") == "recent" for item in direction["factors"]):
            notes.append(
                "交易时段按近 %d 日盘中流向打分，观测不够当长期胜率，只作战术参考。"
                % (session.get("profile_days") or 0)
            )
        elif session.get("hour_samples", 0) < MIN_ZONE_DAYS:
            notes.append(
                "交易时段还没进打分：盘中曲线只折进了 %d 天，少于 %d 天不算数。"
                % (session.get("profile_days") or 0, MIN_ZONE_DAYS)
            )
        if session.get("hour_vol_rank_pct") is not None:
            notes.append(
                "这个钟点的金价振幅处在已观测小时的第 %d 百分位。"
                % session["hour_vol_rank_pct"]
            )
        hot_open = _hot_open_names(session)
        if hot_open:
            notes.append("当前开着、近两日金价波动较大的交易所：%s。" % "、".join(hot_open[:3]))
        boost = _vol_boost(session)
        if boost > 1.01:
            notes.append("这个钟点波动偏大，买入卖出档按 %.0f%% 放宽。" % ((boost - 1) * 100))
    if regime and regime.get("volume_rank_pct") is not None:
        # 原先这里写「声量高的日子次日振幅更大」，实测 r 只有 0.04 且分区不单调，
        # 站不住，改成只报位置不下结论
        notes.append(
            "事件声量处在近半年的第 %d 百分位，仅供参考：实测声量高低和次日振幅没有稳定关系。"
            % regime["volume_rank_pct"]
        )
    notes.append(
        "价位由沪金日线换算而来，基差取%s，比例 %.4f。" % (basis["source"], scale)
    )
    notes.append("ATR14 为 %.2f 元，代表最近一天的正常波动幅度。" % atr)
    notes.append(
        "事件只影响方向倾向和档位宽度。胜率都是实测值，只有一百来个交易日，"
        "统计上还达不到显著，别当准确率看。"
    )
    notes.append("这是按规则算出的参考位，不是投资建议。")

    return {
        "ready": True,
        "price": price,
        "stance": stance,
        "headline": headline,
        "score": score,
        "factors": direction["factors"],
        "z_score": _round(z),
        "ma20": _round(ma20),
        "ma60": _round(ma60),
        "atr": _round(atr),
        "swing_high": _round(swing_high),
        "swing_low": _round(swing_low),
        "breakeven": _round(breakeven),
        "avg_cost": _round(position.get("avg_cost")),
        "total_grams": position.get("total_grams"),
        "net_if_sell_now": position.get("net_if_sell_now"),
        "buy_levels": buy_levels,
        "sell_levels": sell_levels,
        "notes": notes,
    }


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

    holdings = list_holdings(db)
    conditions = measure(db)
    session = session_snapshot(db)
    tape = _recent_tape(db, price)
    result = evaluate(
        price,
        bars,
        _basis_scale(db, bars, price),
        {
            "breakeven": holdings.breakeven_sell,
            "avg_cost": holdings.avg_cost,
            "total_grams": holdings.total_grams,
            "net_if_sell_now": holdings.net_if_sell_now,
        },
        regime=conditions,
        session=session,
        tape=tape,
    )
    if not result.get("ready"):
        return result
    result["as_of"] = quote.collected_at
    result["trade_date"] = quote.trade_date
    if conditions.get("ready"):
        result["drivers"] = conditions["drivers"]
        result["mood_label"] = conditions["mood_label"]
        result["polarity"] = conditions["polarity"]
        result["volume_rank_pct"] = conditions["volume_rank_pct"]
    else:
        result["drivers"] = _recent_drivers(db)
    result["session"] = {
        "band": session.get("band"),
        "band_label": session.get("band_label"),
        "clock": session.get("clock"),
        "open_count": session.get("open_count"),
        "open_names": session.get("open_names"),
        "hour_vol_rank_pct": session.get("hour_vol_rank_pct"),
        "profile_days": session.get("profile_days"),
        "hot_names": [item["name"] for item in session.get("exchanges") or [] if item.get("hot")][:3],
        "hot_open": _hot_open_names(session),
    }
    return result
