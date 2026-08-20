"""研究：某类事件异常放量之后，下一个交易日的金价往哪走。

结论用来给买卖建议加一个事件维度。只是研究脚本，不参与线上逻辑。
"""

import statistics
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analysis.attribution import PRIMARY_TAGS
from app.collectors.flashes import load_flashes
from app.collectors.history import load_bars
from app.config import settings
from app.database import SessionLocal
from app.timeutil import now_local


def main() -> None:
    db = SessionLocal()
    end = now_local().date()
    start = end - timedelta(days=180)
    bars = load_bars(db, start, end)
    trading = {bar["trade_date"]: bar for bar in bars}
    order = [bar["trade_date"] for bar in bars]
    index_of = {day: i for i, day in enumerate(order)}

    flashes = load_flashes(db, start)
    by_day = defaultdict(list)
    for flash in flashes:
        day = flash.session_date
        if day not in trading:
            # 周末顺延到下一个交易日
            cursor = day
            for _ in range(6):
                nxt = (
                    __import__("datetime").date.fromisoformat(cursor) + timedelta(days=1)
                ).isoformat()
                cursor = nxt
                if nxt in trading:
                    day = nxt
                    break
            else:
                continue
        by_day[day].append(flash)

    # 每天各类型的加权声量
    day_scores = {}
    for day in order:
        scores = defaultdict(float)
        for flash in by_day.get(day, []):
            for tag in flash.tags.split(","):
                if tag in PRIMARY_TAGS:
                    scores[tag] += flash.weight or 1.0
        day_scores[day] = dict(scores)

    totals = defaultdict(float)
    for scores in day_scores.values():
        for tag, score in scores.items():
            totals[tag] += score
    grand = sum(totals.values())
    baseline = {tag: score / grand for tag, score in totals.items()}

    print("覆盖 %s 个交易日，%s 条快讯" % (len(order), len(flashes)))
    print("各类型平常声量占比：")
    for tag, share in sorted(baseline.items(), key=lambda x: x[1], reverse=True):
        print("  %-4s %5.1f%%" % (tag, share * 100))

    all_returns = [
        trading[day]["change_pct"] for day in order if trading[day]["change_pct"] is not None
    ]
    drift_all = statistics.fmean(all_returns)
    print("\n全期日均涨跌 %+.3f%%，日均振幅 %.2f%%" % (drift_all, statistics.fmean(abs(r) for r in all_returns)))

    # 挑出每天异常放量的类型
    loud = defaultdict(list)
    for day in order:
        scores = day_scores[day]
        total = sum(scores.values())
        if not total:
            continue
        excess = {tag: score / total - baseline.get(tag, 0.0) for tag, score in scores.items()}
        ranked = sorted(excess.items(), key=lambda x: x[1], reverse=True)
        top = ranked[0][1]
        if top <= 0:
            continue
        for tag, value in ranked[: settings.max_tags_per_day]:
            if value > 0 and value >= top * settings.tag_score_ratio:
                loud[tag].append(day)

    print("\n%-4s %4s %10s %10s %10s %8s %8s" % ("类型", "天数", "当日涨跌", "次日涨跌", "次日振幅", "次日胜率", "t 值"))
    rows = []
    for tag in PRIMARY_TAGS:
        days = loud.get(tag, [])
        same, nxt = [], []
        for day in days:
            i = index_of[day]
            if trading[day]["change_pct"] is not None:
                same.append(trading[day]["change_pct"])
            if i + 1 < len(order):
                value = trading[order[i + 1]]["change_pct"]
                if value is not None:
                    nxt.append(value)
        if len(nxt) < 5:
            print("%-4s %4d  样本不足" % (tag, len(days)))
            continue
        mean_next = statistics.fmean(nxt)
        sd = statistics.stdev(nxt) if len(nxt) > 1 else 0.0
        t = mean_next / (sd / len(nxt) ** 0.5) if sd else 0.0
        win = sum(1 for v in nxt if v > 0) / len(nxt)
        rows.append((tag, len(days), statistics.fmean(same), mean_next, statistics.fmean(abs(v) for v in nxt), win, t))
        print(
            "%-4s %4d %+9.2f%% %+9.2f%% %9.2f%% %7.0f%% %8.2f"
            % (tag, len(days), rows[-1][2], mean_next, rows[-1][4], win * 100, t)
        )

    print("\n对照：随机一天的次日涨跌 %+.3f%%，胜率 %.0f%%" % (
        drift_all,
        sum(1 for r in all_returns if r > 0) / len(all_returns) * 100,
    ))

    # 声量总量本身是不是波动放大的信号
    print("\n快讯总声量分档 → 次日振幅：")
    volumes = sorted((sum(day_scores[day].values()), day) for day in order)
    third = len(volumes) // 3
    for label, chunk in (("低", volumes[:third]), ("中", volumes[third : 2 * third]), ("高", volumes[2 * third :])):
        moves = []
        for _, day in chunk:
            i = index_of[day]
            if i + 1 < len(order) and trading[order[i + 1]]["change_pct"] is not None:
                moves.append(abs(trading[order[i + 1]]["change_pct"]))
        if moves:
            print("  %s声量 %3d 天 → 次日平均振幅 %.2f%%" % (label, len(chunk), statistics.fmean(moves)))

    # 关键问题：均值回归和动量分别在什么环境下有效
    print("\n=== 均值回归 vs 动量，按事件声量分档 ===")
    closes = [bar["close"] for bar in bars]
    rows = []
    for i, day in enumerate(order):
        if i < 20 or i + 1 >= len(order):
            continue
        nxt = trading[order[i + 1]]["change_pct"]
        if nxt is None:
            continue
        ma20 = sum(closes[i - 19 : i + 1]) / 20
        ranges = []
        for j in range(max(1, i - 13), i + 1):
            prev = closes[j - 1]
            bar = bars[j]
            if bar["high"] is None or bar["low"] is None:
                continue
            ranges.append(max(bar["high"] - bar["low"], abs(bar["high"] - prev), abs(bar["low"] - prev)))
        atr = statistics.fmean(ranges) if ranges else None
        if not atr:
            continue
        z = (closes[i] - ma20) / atr
        momentum = (closes[i] / closes[i - 5] - 1) * 100
        rows.append(
            {
                "day": day,
                "z": z,
                "momentum": momentum,
                "next": nxt,
                "volume": sum(day_scores[day].values()),
            }
        )

    def corr(xs, ys):
        if len(xs) < 8:
            return 0.0
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
        return num / den if den else 0.0

    rows.sort(key=lambda r: r["volume"])
    third = len(rows) // 3
    buckets = (
        ("低声量", rows[:third]),
        ("中声量", rows[third : 2 * third]),
        ("高声量", rows[2 * third :]),
    )
    print("%-6s %4s %14s %12s" % ("环境", "天数", "-z 与次日相关", "动量与次日相关"))
    for label, chunk in buckets:
        if not chunk:
            continue
        print(
            "%-6s %4d %13.2f %13.2f"
            % (
                label,
                len(chunk),
                corr([-r["z"] for r in chunk], [r["next"] for r in chunk]),
                corr([r["momentum"] for r in chunk], [r["next"] for r in chunk]),
            )
        )
    print(
        "%-6s %4d %13.2f %13.2f"
        % (
            "全样本",
            len(rows),
            corr([-r["z"] for r in rows], [r["next"] for r in rows]),
            corr([r["momentum"] for r in rows], [r["next"] for r in rows]),
        )
    )

    print("\n=== 偏离均线很多之后，次日表现（检验均值回归假设）===")
    for label, picked in (
        ("z > +1.5（规则说偏高）", [r for r in rows if r["z"] > 1.5]),
        ("z 在 -1.5~1.5", [r for r in rows if -1.5 <= r["z"] <= 1.5]),
        ("z < -1.5（规则说偏低）", [r for r in rows if r["z"] < -1.5]),
    ):
        if len(picked) < 5:
            print("  %-22s 样本不足 %d" % (label, len(picked)))
            continue
        nxt = [r["next"] for r in picked]
        print(
            "  %-22s %3d 天 → 次日 %+.2f%%，胜率 %.0f%%"
            % (label, len(picked), statistics.fmean(nxt), sum(1 for v in nxt if v > 0) / len(nxt) * 100)
        )

    print("\n=== 大波动之后是延续还是反转 ===")
    for label, picked in (
        ("大涨 ≥ +0.8%", [r for r in rows if trading[r["day"]]["change_pct"] >= 0.8]),
        ("小涨 0~0.8%", [r for r in rows if 0 < trading[r["day"]]["change_pct"] < 0.8]),
        ("小跌 -0.8~0%", [r for r in rows if -0.8 < trading[r["day"]]["change_pct"] <= 0]),
        ("大跌 ≤ -0.8%", [r for r in rows if trading[r["day"]]["change_pct"] <= -0.8]),
    ):
        if len(picked) < 5:
            print("  %-14s 样本不足 %d" % (label, len(picked)))
            continue
        nxt = [r["next"] for r in picked]
        print(
            "  %-14s %3d 天 → 次日 %+.2f%%，同向延续 %.0f%%"
            % (
                label,
                len(picked),
                statistics.fmean(nxt),
                sum(
                    1
                    for r in picked
                    if r["next"] * trading[r["day"]]["change_pct"] > 0
                )
                / len(picked)
                * 100,
            )
        )

    # 新闻的方向性：局势升级通常利多金价，缓和利空。用词表给每天算一个净升级分
    ESCALATE = (
        "袭击", "空袭", "打击", "开战", "升级", "制裁", "报复", "导弹", "无人机",
        "轰炸", "death", "伤亡", "封锁", "威胁", "驱逐", "断交", "增兵", "冲突",
    )
    DEESCALATE = (
        "停火", "和谈", "谈判", "协议", "缓和", "撤军", "释放", "解除", "豁免",
        "对话", "会晤", "重启", "让步", "达成",
    )
    print("\n=== 新闻方向性（升级/缓和）与次日涨跌 ===")
    polarity = {}
    for day in order:
        up = down = 0.0
        for flash in by_day.get(day, []):
            text = flash.title
            weight = flash.weight or 1.0
            if any(word in text for word in ESCALATE):
                up += weight
            if any(word in text for word in DEESCALATE):
                down += weight
        total = up + down
        polarity[day] = (up - down) / total if total else 0.0

    scored = [r for r in rows if r["day"] in polarity]
    print("  升级分与次日相关系数 %.2f（%d 天）" % (
        corr([polarity[r["day"]] for r in scored], [r["next"] for r in scored]),
        len(scored),
    ))
    scored.sort(key=lambda r: polarity[r["day"]])
    cut = len(scored) // 3
    for label, chunk in (
        ("偏缓和", scored[:cut]),
        ("中性", scored[cut : 2 * cut]),
        ("偏升级", scored[2 * cut :]),
    ):
        if len(chunk) < 5:
            continue
        nxt = [r["next"] for r in chunk]
        print(
            "  %-4s %3d 天 → 次日 %+.2f%%，上涨 %.0f%%（当日 %+.2f%%）"
            % (
                label,
                len(chunk),
                statistics.fmean(nxt),
                sum(1 for v in nxt if v > 0) / len(nxt) * 100,
                statistics.fmean(trading[r["day"]]["change_pct"] for r in chunk),
            )
        )

    # 偏升级的日子往往当天就在跌，得先剔掉「跌了就反弹」这个已知效应
    print("\n  控制当日涨跌后（偏相关）：")
    xs = [polarity[r["day"]] for r in scored]
    ys = [r["next"] for r in scored]
    zs = [trading[r["day"]]["change_pct"] for r in scored]

    def residuals(target, control):
        mc = statistics.fmean(control)
        mt = statistics.fmean(target)
        var = sum((c - mc) ** 2 for c in control)
        beta = sum((c - mc) * (t - mt) for c, t in zip(control, target)) / var if var else 0.0
        return [t - (mt + beta * (c - mc)) for t, c in zip(target, control)]

    print(
        "    升级分与次日的偏相关 %.2f（原始 %.2f）"
        % (corr(residuals(xs, zs), residuals(ys, zs)), corr(xs, ys))
    )

    print("  只看当日下跌的日子：")
    down_days = [r for r in scored if trading[r["day"]]["change_pct"] < 0]
    down_days.sort(key=lambda r: polarity[r["day"]])
    half = len(down_days) // 2
    for label, chunk in (("升级分低", down_days[:half]), ("升级分高", down_days[half:])):
        if len(chunk) < 5:
            continue
        nxt = [r["next"] for r in chunk]
        print(
            "    %-6s %3d 天 → 次日 %+.2f%%，上涨 %.0f%%"
            % (label, len(chunk), statistics.fmean(nxt), sum(1 for v in nxt if v > 0) / len(nxt) * 100)
        )

    print("\n=== 高声量 + 大波动（事件驱动的行情）之后 ===")
    volume_cut = statistics.median(r["volume"] for r in rows)
    picked = [
        r
        for r in rows
        if r["volume"] >= volume_cut and abs(trading[r["day"]]["change_pct"]) >= 0.8
    ]
    if len(picked) >= 5:
        nxt = [r["next"] for r in picked]
        same = sum(1 for r in picked if r["next"] * trading[r["day"]]["change_pct"] > 0)
        print(
            "  %3d 天 → 次日 %+.2f%%，平均振幅 %.2f%%，同向延续 %.0f%%"
            % (
                len(picked),
                statistics.fmean(nxt),
                statistics.fmean(abs(v) for v in nxt),
                same / len(picked) * 100,
            )
        )

    db.close()


if __name__ == "__main__":
    main()
