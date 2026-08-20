"""事件类型权重归因。

思路：先挑出显著波动日（|日涨跌幅| 超过阈值），再看当天归属窗口内的快讯都在讲什么。
关键是不能只看「有没有出现」——中东这类话题在冲突期几乎每天都有，属于背景噪音。
所以比的是当天的占比与它在所有显著波动日上的平均占比之差，只有明显放量的类型才算主因，
再把当天的 |涨跌幅| 按主因均摊。
得到的权重是「这段时间的波动幅度里，有多少能记到这类事件上」，是相关归因，不是因果。
"""

import statistics
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..collectors.flashes import load_flashes
from ..collectors.history import load_bars
from ..config import settings
from ..timeutil import now_local

# 只有这些类型参与归因，"金市"/"其他" 说明没有宏观线索
PRIMARY_TAGS = ("美联储", "通胀", "就业", "石油", "央行", "汇率", "利率", "地缘")


def _round(value: Optional[float], digits: int = 2) -> Optional[float]:
    return None if value is None else round(value, digits)


def next_trading_day(day: str, trading_days: set) -> Optional[str]:
    """周末与假期的快讯顺延到下一个交易日。"""
    if day in trading_days:
        return day
    cursor = date.fromisoformat(day)
    for _ in range(6):
        cursor += timedelta(days=1)
        if cursor.isoformat() in trading_days:
            return cursor.isoformat()
    return None


def significant_days(bars: List[Dict], threshold: Optional[float] = None) -> List[Dict]:
    limit = threshold if threshold is not None else settings.significant_move_pct
    return [
        bar for bar in bars if bar["change_pct"] is not None and abs(bar["change_pct"]) >= limit
    ]


def _volatility(bars: List[Dict], close: float) -> Dict:
    returns = [bar["change_pct"] for bar in bars if bar["change_pct"] is not None]
    recent = returns[-20:]
    mid = returns[-60:]
    sd_recent = statistics.pstdev(recent) if len(recent) > 1 else 0.0
    sd_mid = statistics.pstdev(mid) if len(mid) > 1 else 0.0
    sd = (sd_recent + sd_mid) / 2 or sd_recent or sd_mid

    true_ranges = []
    for index in range(1, len(bars)):
        prev_close = bars[index - 1]["close"]
        bar = bars[index]
        if bar["high"] is None or bar["low"] is None:
            continue
        true_ranges.append(
            max(bar["high"] - bar["low"], abs(bar["high"] - prev_close), abs(bar["low"] - prev_close))
        )
    atr = sum(true_ranges[-14:]) / len(true_ranges[-14:]) if true_ranges else None

    def average(window: int) -> Optional[float]:
        subset = bars[-window:]
        return sum(b["close"] for b in subset) / len(subset) if subset else None

    projections = []
    for horizon, label in ((5, "一周"), (10, "两周"), (21, "一个月")):
        sigma = sd * (horizon**0.5)
        projections.append(
            {
                "label": label,
                "trading_days": horizon,
                "sigma_pct": _round(sigma),
                "low": _round(close * (1 - sigma / 100)),
                "high": _round(close * (1 + sigma / 100)),
            }
        )

    highs = [bar["high"] for bar in bars if bar["high"] is not None]
    lows = [bar["low"] for bar in bars if bar["low"] is not None]
    return {
        "daily_sd_20": _round(sd_recent),
        "daily_sd_60": _round(sd_mid),
        "mean_abs_move": _round(sum(abs(r) for r in returns) / len(returns)) if returns else None,
        "atr14": _round(atr),
        "atr14_pct": _round(atr / close * 100) if atr else None,
        "ma20": _round(average(20)),
        "ma60": _round(average(60)),
        "window_high": _round(max(highs)) if highs else None,
        "window_low": _round(min(lows)) if lows else None,
        "projections": projections,
    }


def compute_attribution(
    db: Session,
    window_days: Optional[int] = None,
    threshold: Optional[float] = None,
) -> Dict:
    window = window_days or settings.attribution_window_days
    end = now_local().date()
    start = end - timedelta(days=window)
    bars = load_bars(db, start - timedelta(days=20), end)
    bars = [bar for bar in bars if bar["trade_date"] >= start.isoformat()]
    if len(bars) < 2:
        return {
            "ready": False,
            "message": "历史日线还没同步，先调用 POST /api/analysis/refresh",
            "window_days": window,
        }

    trading_days = {bar["trade_date"]: bar for bar in bars}
    flashes = load_flashes(db, start)

    # 快讯按交易日归堆
    by_day: Dict[str, List] = defaultdict(list)
    for flash in flashes:
        day = next_trading_day(flash.session_date, set(trading_days))
        if day:
            by_day[day].append(flash)

    sig = significant_days(bars, threshold)

    # 第一遍：统计每个显著波动日各类型的加权声量，以及可用于展示的标题
    day_scores: Dict[str, Dict[str, float]] = {}
    day_headlines: Dict[str, Dict[str, str]] = {}
    for bar in sig:
        scores: Dict[str, float] = defaultdict(float)
        headline_of: Dict[str, str] = {}
        best_weight: Dict[str, float] = {}
        for flash in by_day.get(bar["trade_date"], []):
            weight = flash.weight or 1.0
            for tag in flash.tags.split(","):
                if tag not in PRIMARY_TAGS:
                    continue
                scores[tag] += weight
                # 用当天该类型里最重要的一条当代表标题
                if weight > best_weight.get(tag, 0.0):
                    best_weight[tag] = weight
                    headline_of[tag] = flash.title
        day_scores[bar["trade_date"]] = dict(scores)
        day_headlines[bar["trade_date"]] = headline_of

    # 各类型在显著波动日上的平均占比，作为「正常声量」的基准
    totals: Dict[str, float] = defaultdict(float)
    for scores in day_scores.values():
        for tag, score in scores.items():
            totals[tag] += score
    grand_total = sum(totals.values())
    baseline_share = {
        tag: (score / grand_total if grand_total else 0.0) for tag, score in totals.items()
    }

    impact: Dict[str, float] = defaultdict(float)
    day_count: Dict[str, int] = defaultdict(int)
    abs_sum: Dict[str, float] = defaultdict(float)
    signed_sum: Dict[str, float] = defaultdict(float)
    monthly: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    assigned: List[Dict] = []
    unattributed = 0
    unattributed_abs = 0.0

    for bar in sig:
        scores = day_scores[bar["trade_date"]]
        headline_of = day_headlines[bar["trade_date"]]
        day_total = sum(scores.values())
        if not day_total:
            unattributed += 1
            unattributed_abs += abs(bar["change_pct"])
            assigned.append({**bar, "tags": [], "headline": "", "headlines": {}})
            continue

        # 超出基准的部分才算异常放量
        excess = {
            tag: score / day_total - baseline_share.get(tag, 0.0)
            for tag, score in scores.items()
        }
        ranked = sorted(excess.items(), key=lambda item: item[1], reverse=True)
        top_excess = ranked[0][1]
        if top_excess <= 0:
            # 当天没有任何类型放量，退回到声量最高的那个
            tags = [ranked[0][0]]
        else:
            tags = [
                tag
                for tag, value in ranked
                if value > 0 and value >= top_excess * settings.tag_score_ratio
            ][: settings.max_tags_per_day]

        share = abs(bar["change_pct"]) / len(tags)
        for tag in tags:
            impact[tag] += share
            day_count[tag] += 1
            abs_sum[tag] += abs(bar["change_pct"])
            signed_sum[tag] += bar["change_pct"]
            monthly[bar["trade_date"][:7]][tag] += share
        assigned.append(
            {
                **bar,
                "tags": tags,
                "headline": headline_of.get(tags[0], ""),
                "headlines": headline_of,
            }
        )

    total_impact = sum(impact.values())
    all_abs = [abs(bar["change_pct"]) for bar in bars if bar["change_pct"] is not None]
    baseline = sum(all_abs) / len(all_abs) if all_abs else 0.0

    types = []
    for tag, value in sorted(impact.items(), key=lambda item: item[1], reverse=True):
        count = day_count[tag]
        avg_abs = abs_sum[tag] / count
        types.append(
            {
                "tag": tag,
                "weight_pct": _round(value / total_impact * 100, 1) if total_impact else 0.0,
                "impact_points": _round(value),
                "days": count,
                "avg_abs_move": _round(avg_abs),
                "avg_move": _round(signed_sum[tag] / count),
                "lift": _round(avg_abs / baseline) if baseline else None,
                "baseline_share_pct": _round(baseline_share.get(tag, 0.0) * 100, 1),
                "sample_headline": next(
                    (
                        item["headlines"].get(tag, "")
                        for item in assigned
                        if tag in item["tags"] and item["headlines"].get(tag)
                    ),
                    "",
                ),
            }
        )

    top_moves = sorted(
        assigned, key=lambda item: abs(item["change_pct"]), reverse=True
    )[:12]

    return {
        "ready": True,
        "window_days": window,
        "start_date": bars[0]["trade_date"],
        "end_date": bars[-1]["trade_date"],
        "proxy_symbol": settings.proxy_symbol,
        "threshold_pct": threshold if threshold is not None else settings.significant_move_pct,
        "bar_count": len(bars),
        "flash_count": len(flashes),
        "significant_days": len(sig),
        "start_close": _round(bars[0]["close"]),
        "end_close": _round(bars[-1]["close"]),
        "total_change_pct": _round((bars[-1]["close"] / bars[0]["close"] - 1) * 100, 1),
        "baseline_abs_move": _round(baseline),
        "attributed_points": _round(total_impact),
        "unattributed_days": unattributed,
        "unattributed_points": _round(unattributed_abs),
        "types": types,
        "monthly": [
            {"month": month, "tags": {tag: _round(value) for tag, value in sorted(tags.items(), key=lambda i: i[1], reverse=True)}}
            for month, tags in sorted(monthly.items())
        ],
        "top_moves": [
            {
                "trade_date": item["trade_date"],
                "change_pct": item["change_pct"],
                "close": _round(item["close"]),
                "tags": item["tags"],
                "headline": item["headline"],
            }
            for item in top_moves
        ],
        "volatility": _volatility(bars, bars[-1]["close"]),
    }


def days_needing_narrative(db: Session, window_days: Optional[int] = None) -> List[str]:
    """显著波动日里还缺叙事快讯的日子，交给采集器去补。"""
    window = window_days or settings.attribution_window_days
    end = now_local().date()
    start = end - timedelta(days=window)
    bars = load_bars(db, start - timedelta(days=20), end)
    bars = [bar for bar in bars if bar["trade_date"] >= start.isoformat()]
    return [bar["trade_date"] for bar in significant_days(bars)]
