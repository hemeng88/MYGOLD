"""回看：某个交易日收盘时，这套规则会给什么建议。

胜率只用该日之前的数据拟合，避免用到未来信息。
用法：python backend/scripts/advice_asof.py 2026-08-19 2026-08-20
"""

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.analysis.advice import evaluate
from app.analysis.regime import POLARITY_EDGE, _series
from app.database import SessionLocal
from backtest_advice import build_samples, fit, mood_of


def main() -> None:
    targets = sys.argv[1:]
    db = SessionLocal()
    data = _series(db, 180)
    bars, days = data["bars"], data["days"]
    samples = build_samples(bars, days)
    sample_at = {s["day"]: s for s in samples}
    index_of = {bar["trade_date"]: i for i, bar in enumerate(bars)}

    # 基差用今天的比例，历史上没有积存金报价可对
    scale = 968.30 / bars[-1]["close"]

    for target in targets:
        if target not in index_of:
            print("%s 不是交易日或超出范围" % target)
            continue
        i = index_of[target]
        past = [s for s in samples if s["day"] < target]
        if len(past) < 25:
            print("%s 之前样本不足" % target)
            continue
        fitted = fit(past)
        polarity = (
            statistics.fmean([days[i - 1]["polarity"], days[i]["polarity"]])
            if i >= 1
            else days[i]["polarity"]
        )
        mood, mood_label = mood_of(polarity)
        regime = dict(fitted)
        regime.update({"mood": mood, "mood_label": mood_label, "polarity": polarity})

        window = bars[: i + 1]
        price = window[-1]["close"] * scale
        result = evaluate(
            price,
            window,
            {"scale": scale, "source": "今日基差", "sample_days": 1},
            {},
            regime=regime,
        )
        nxt = bars[i + 1]["change_pct"] if i + 1 < len(bars) else None

        print("=== %s 收盘 ===" % target)
        print(
            "  换算价 %.2f | 偏离均线 %.2f 个 ATR | 新闻%s（%+.2f）"
            % (result["price"], result["z_score"], mood_label, polarity)
        )
        print("  倾向 %s（总分 %+.2f）：%s" % (result["stance"], result["score"], result["headline"]))
        for factor in result["factors"]:
            print(
                "    %s %+.2f ← 历史 %d 天，次日上涨 %d%%"
                % (factor["label"], factor["score"], factor["days"], factor["win_rate"])
            )
        if nxt is not None:
            print("  实际次日 %+.2f%%" % nxt)
        print()

    db.close()


if __name__ == "__main__":
    main()
