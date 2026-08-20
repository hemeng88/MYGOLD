"""样本外回测：用前半段算胜率，在后半段检验新旧规则。

同一段数据既拟合又检验等于自欺，所以按时间切一刀。
比较的指标很直接：规则说「可以买」的那些天，第二天平均涨了多少。
"""

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analysis.advice import _direction_score
from app.analysis.regime import POLARITY_EDGE, _series
from app.database import SessionLocal


def win_stats(values):
    if len(values) < 5:
        return None
    return {
        "days": len(values),
        "mean_next": round(statistics.fmean(values), 2),
        "win_rate": round(sum(1 for v in values if v > 0) / len(values) * 100),
    }


def build_samples(bars, days):
    closes = [bar["close"] for bar in bars]
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
        samples.append(
            {
                "day": bars[i]["trade_date"],
                "z": (closes[i] - ma20) / statistics.fmean(ranges),
                "polarity": days[i]["polarity"],
                "next": nxt,
            }
        )
    return samples


def zone_of(z):
    if z <= -1.0:
        return "low"
    if z >= 1.5:
        return "high"
    return "mid"


def mood_of(polarity):
    if polarity >= POLARITY_EDGE:
        return "escalate", "偏升级"
    if polarity <= -POLARITY_EDGE:
        return "calm", "偏缓和"
    return "neutral", "中性"


def fit(samples):
    return {
        "ready": True,
        "position_zones": {
            key: win_stats([s["next"] for s in samples if zone_of(s["z"]) == key])
            for key in ("low", "mid", "high")
        },
        "polarity_zones": {
            key: win_stats([s["next"] for s in samples if mood_of(s["polarity"])[0] == key])
            for key in ("escalate", "neutral", "calm")
        },
    }


def report(label, picked, everything):
    if not picked:
        print("  %-16s 没有触发" % label)
        return
    nxt = [s["next"] for s in picked]
    print(
        "  %-16s %3d 天 → 次日 %+.2f%%，上涨 %.0f%%"
        % (label, len(picked), statistics.fmean(nxt), sum(1 for v in nxt if v > 0) / len(nxt) * 100)
    )


def main() -> None:
    db = SessionLocal()
    data = _series(db, 180)
    bars, days = data["bars"], data["days"]
    samples = build_samples(bars, days)
    cut = len(samples) // 2
    train, test = samples[:cut], samples[cut:]
    print(
        "训练 %d 天（%s 起），检验 %d 天（%s 起）"
        % (len(train), train[0]["day"], len(test), test[0]["day"])
    )

    fitted = fit(train)
    print("\n前半段拟合出的胜率：")
    for group, name in (("position_zones", "位置"), ("polarity_zones", "事件")):
        for key, stats in fitted[group].items():
            if stats:
                print(
                    "  %s/%-9s %3d 天，次日上涨 %2d%%，均值 %+.2f%%"
                    % (name, key, stats["days"], stats["win_rate"], stats["mean_next"])
                )

    scored = []
    for sample in test:
        mood, mood_label = mood_of(sample["polarity"])
        regime = dict(fitted)
        regime.update({"mood": mood, "mood_label": mood_label, "polarity": sample["polarity"]})
        result = _direction_score(sample["z"], regime)
        scored.append({**sample, "score": result["score"]})

    all_next = [s["next"] for s in test]
    print(
        "\n检验段基准：%d 天，次日 %+.2f%%，上涨 %.0f%%"
        % (
            len(all_next),
            statistics.fmean(all_next),
            sum(1 for v in all_next if v > 0) / len(all_next) * 100,
        )
    )

    print("\n新规则（位置 + 事件方向，门槛 ±0.10）：")
    report("说买入", [s for s in scored if s["score"] >= 0.10], all_next)
    report("说观望", [s for s in scored if -0.10 < s["score"] < 0.10], all_next)
    report("说别加仓", [s for s in scored if s["score"] <= -0.10], all_next)

    print("\n旧规则（只看偏离均线）：")
    report("说买入", [s for s in test if s["z"] <= -1.0], all_next)
    report("说观望", [s for s in test if -1.0 < s["z"] < 1.5], all_next)
    report("说等回踩", [s for s in test if s["z"] >= 1.5], all_next)

    print("\n只用事件方向：")
    report("偏升级", [s for s in test if s["polarity"] >= POLARITY_EDGE], all_next)
    report("中性", [s for s in test if -POLARITY_EDGE < s["polarity"] < POLARITY_EDGE], all_next)
    report("偏缓和", [s for s in test if s["polarity"] <= -POLARITY_EDGE], all_next)

    db.close()


if __name__ == "__main__":
    main()
