"""事件环境：新闻的方向性、声量热度，以及这两者在历史上的表现。

为什么用「升级 / 缓和」而不是事件类型：实测下来事件类型（美联储、通胀、地缘…）
对次日方向没有可用信号，t 值全在 ±1.3 以内。但新闻本身的方向性有——
局势升级利多避险，缓和利空，偏相关 0.17，而且剔掉「跌了就反弹」这个效应之后依然成立。

所有胜率都是从库里实时算出来的，不写死，样本量一并返回，方便判断结论有多薄。
"""

import statistics
from collections import defaultdict
from datetime import timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..collectors.flashes import load_flashes
from ..collectors.history import load_bars
from ..config import settings
from ..timeutil import now_local
from .attribution import PRIMARY_TAGS, next_trading_day

# 升级类措辞：冲突加剧、制裁、袭击，通常推高避险需求
ESCALATE = (
    "袭击", "空袭", "打击", "开战", "升级", "制裁", "报复", "导弹", "无人机",
    "轰炸", "伤亡", "封锁", "威胁", "驱逐", "断交", "增兵", "冲突", "扣押",
)
# 缓和类措辞：停火、谈判、豁免
DEESCALATE = (
    "停火", "和谈", "谈判", "协议", "缓和", "撤军", "释放", "解除", "豁免",
    "对话", "会晤", "重启", "让步", "达成", "和平",
)

# 判定「偏升级 / 偏缓和」的门槛，正负对称
POLARITY_EDGE = 0.15


def polarity_of(text: str) -> int:
    hit_up = any(word in text for word in ESCALATE)
    hit_down = any(word in text for word in DEESCALATE)
    if hit_up and not hit_down:
        return 1
    if hit_down and not hit_up:
        return -1
    return 0


def _series(db: Session, window_days: int) -> Dict:
    """按交易日汇总声量、升级分和涨跌，作为后面所有统计的底稿。"""
    end = now_local().date()
    start = end - timedelta(days=window_days)
    bars = load_bars(db, start - timedelta(days=30), end)
    bars = [bar for bar in bars if bar["trade_date"] >= start.isoformat()]
    if len(bars) < 25:
        return {"ready": False, "bars": bars, "days": []}

    trading = {bar["trade_date"]: bar for bar in bars}
    keys = set(trading)
    buckets: Dict[str, List] = defaultdict(list)
    for flash in load_flashes(db, start):
        day = next_trading_day(flash.session_date, keys)
        if day:
            buckets[day].append(flash)

    days = []
    for bar in bars:
        up = down = volume = 0.0
        tags: Dict[str, float] = defaultdict(float)
        for flash in buckets.get(bar["trade_date"], []):
            weight = flash.weight or 1.0
            volume += weight
            mood = polarity_of(flash.title)
            if mood > 0:
                up += weight
            elif mood < 0:
                down += weight
            for tag in flash.tags.split(","):
                if tag in PRIMARY_TAGS:
                    tags[tag] += weight
        total = up + down
        days.append(
            {
                "trade_date": bar["trade_date"],
                "change_pct": bar["change_pct"],
                "volume": volume,
                "polarity": (up - down) / total if total else 0.0,
                "tags": dict(tags),
            }
        )
    return {"ready": True, "bars": bars, "days": days}


def _win_stats(values: List[float]) -> Optional[Dict]:
    if len(values) < 5:
        return None
    return {
        "days": len(values),
        "mean_next": round(statistics.fmean(values), 2),
        "win_rate": round(sum(1 for v in values if v > 0) / len(values) * 100),
    }


def measure(db: Session, window_days: Optional[int] = None) -> Dict:
    """算出位置分区和升级分区在历史上的次日表现，以及当下处在哪个区。"""
    window = window_days or settings.attribution_window_days
    data = _series(db, window)
    if not data["ready"]:
        return {"ready": False, "message": "历史数据不足，先在归因页点一次更新"}

    bars = data["bars"]
    days = data["days"]
    closes = [bar["close"] for bar in bars]

    # 逐日算出位置（偏离 MA20 几个 ATR）和次日涨跌，供分区统计
    samples = []
    for i in range(20, len(bars) - 1):
        nxt = bars[i + 1]["change_pct"]
        if nxt is None:
            continue
        ma20 = sum(closes[i - 19 : i + 1]) / 20
        ranges = []
        for j in range(max(1, i - 13), i + 1):
            bar = bars[j]
            if bar["high"] is None or bar["low"] is None:
                continue
            prev = closes[j - 1]
            ranges.append(
                max(bar["high"] - bar["low"], abs(bar["high"] - prev), abs(bar["low"] - prev))
            )
        if not ranges:
            continue
        atr = statistics.fmean(ranges)
        samples.append(
            {
                "z": (closes[i] - ma20) / atr,
                "polarity": days[i]["polarity"],
                "volume": days[i]["volume"],
                "next": nxt,
            }
        )

    position_zones = {
        "low": _win_stats([s["next"] for s in samples if s["z"] <= -1.0]),
        "mid": _win_stats([s["next"] for s in samples if -1.0 < s["z"] < 1.5]),
        "high": _win_stats([s["next"] for s in samples if s["z"] >= 1.5]),
    }
    polarity_zones = {
        "escalate": _win_stats([s["next"] for s in samples if s["polarity"] >= POLARITY_EDGE]),
        "neutral": _win_stats(
            [s["next"] for s in samples if -POLARITY_EDGE < s["polarity"] < POLARITY_EDGE]
        ),
        "calm": _win_stats([s["next"] for s in samples if s["polarity"] <= -POLARITY_EDGE]),
    }

    volumes = sorted(day["volume"] for day in days)
    moves = [abs(day["change_pct"]) for day in days if day["change_pct"] is not None]
    baseline_abs = statistics.fmean(moves) if moves else None

    # 当下：取最近两个交易日，昨天的消息今天还在发酵
    recent = days[-2:]
    recent_volume = statistics.fmean(day["volume"] for day in recent)
    weights = [day["volume"] for day in recent]
    recent_polarity = (
        sum(day["polarity"] * day["volume"] for day in recent) / sum(weights)
        if sum(weights)
        else 0.0
    )
    rank = sum(1 for value in volumes if value <= recent_volume) / len(volumes)

    tags: Dict[str, float] = defaultdict(float)
    for day in recent:
        for tag, score in day["tags"].items():
            tags[tag] += score
    tag_total = sum(tags.values())
    drivers = [
        {"tag": tag, "share_pct": round(score / tag_total * 100, 1)}
        for tag, score in sorted(tags.items(), key=lambda item: item[1], reverse=True)[:3]
    ] if tag_total else []

    if recent_polarity >= POLARITY_EDGE:
        mood, mood_label = "escalate", "偏升级"
    elif recent_polarity <= -POLARITY_EDGE:
        mood, mood_label = "calm", "偏缓和"
    else:
        mood, mood_label = "neutral", "中性"

    return {
        "ready": True,
        "window_days": window,
        "sample_days": len(samples),
        "polarity": round(recent_polarity, 2),
        "mood": mood,
        "mood_label": mood_label,
        "volume_rank_pct": round(rank * 100),
        "baseline_abs_move": round(baseline_abs, 2) if baseline_abs else None,
        "position_zones": position_zones,
        "polarity_zones": polarity_zones,
        "drivers": drivers,
    }
