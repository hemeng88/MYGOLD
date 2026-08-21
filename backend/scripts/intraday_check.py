"""对照某一天的盘中大波段和当时的快讯，看事件方向对不对得上。

日线算法给的是「明天偏多还是偏空」，本来不预测盘中拐点。这个脚本换个问法：
每一波急涨急跌启动之前的一小时里，出现的是升级类还是缓和类消息。

用法：python backend/scripts/intraday_check.py 2026-08-20
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.analysis.regime import polarity_of
from app.database import SessionLocal
from app.models import CurvePoint, NewsFlash
from app.timeutil import from_unix_seconds

# 一波至少要走这么多才算大波段，太小的都是噪音
SWING_PCT = 0.35
LOOKBACK_MINUTES = 60


def find_swings(points, threshold_pct):
    """ZigZag：确认一个转折点，直到反向走够阈值才换方向。"""

    def pct(a, b):
        return (b["price"] / a["price"] - 1) * 100

    swings = []
    pivot = extreme = points[0]
    direction = 0
    for point in points[1:]:
        if direction == 0:
            if pct(pivot, point) >= threshold_pct:
                direction, extreme = 1, point
            elif pct(pivot, point) <= -threshold_pct:
                direction, extreme = -1, point
            continue
        if direction == 1:
            if point["price"] > extreme["price"]:
                extreme = point
            elif pct(extreme, point) <= -threshold_pct:
                swings.append((pivot, extreme, "up"))
                pivot, extreme, direction = extreme, point, -1
        else:
            if point["price"] < extreme["price"]:
                extreme = point
            elif pct(extreme, point) >= threshold_pct:
                swings.append((pivot, extreme, "down"))
                pivot, extreme, direction = extreme, point, 1
    if direction and abs(pct(pivot, extreme)) >= threshold_pct:
        swings.append((pivot, extreme, "up" if direction == 1 else "down"))
    return swings


def main() -> None:
    day = sys.argv[1] if len(sys.argv) > 1 else "2026-08-20"
    db = SessionLocal()
    rows = db.scalars(
        select(CurvePoint).where(CurvePoint.trade_date == day).order_by(CurvePoint.ts)
    ).all()
    if not rows:
        print("%s 没有曲线数据" % day)
        return
    points = [
        {"ts": row.ts, "at": from_unix_seconds(row.ts), "price": row.price} for row in rows
    ]
    print(
        "%s 共 %d 个点，%s—%s，最低 %.2f 最高 %.2f"
        % (
            day,
            len(points),
            points[0]["at"].strftime("%H:%M"),
            points[-1]["at"].strftime("%H:%M"),
            min(p["price"] for p in points),
            max(p["price"] for p in points),
        )
    )

    # 当天前后的快讯都取上，盘中要按真实时间对齐
    start = datetime.combine(points[0]["at"].date() - timedelta(days=1), datetime.min.time())
    end = points[-1]["at"] + timedelta(hours=1)
    flashes = db.scalars(
        select(NewsFlash)
        .where(NewsFlash.published_at >= start, NewsFlash.published_at <= end)
        .order_by(NewsFlash.published_at)
    ).all()
    print("可对齐的快讯 %d 条\n" % len(flashes))

    swings = find_swings(points, SWING_PCT)
    hit = miss = blank = 0
    for anchor, extreme, way in swings:
        move = (extreme["price"] / anchor["price"] - 1) * 100
        window_start = anchor["at"] - timedelta(minutes=LOOKBACK_MINUTES)
        before = [f for f in flashes if window_start <= f.published_at <= anchor["at"]]
        up = sum(1 for f in before if polarity_of(f.title) > 0)
        down = sum(1 for f in before if polarity_of(f.title) < 0)
        if up > down:
            call, mark = "偏升级 → 看涨", "up"
        elif down > up:
            call, mark = "偏缓和 → 看跌", "down"
        else:
            call, mark = "无方向信号", None
        if mark is None:
            blank += 1
            verdict = "—"
        elif mark == way:
            hit += 1
            verdict = "对"
        else:
            miss += 1
            verdict = "错"

        print(
            "%s—%s  %+.2f%%（%.2f → %.2f）%s"
            % (
                anchor["at"].strftime("%H:%M"),
                extreme["at"].strftime("%H:%M"),
                move,
                anchor["price"],
                extreme["price"],
                "  ↑" if way == "up" else "  ↓",
            )
        )
        print("   启动前 1 小时：升级 %d 条 / 缓和 %d 条 → %s  [%s]" % (up, down, call, verdict))
        for flash in before[-3:]:
            mood = polarity_of(flash.title)
            tag = "升级" if mood > 0 else ("缓和" if mood < 0 else "中性")
            print(
                "     %s [%s] %s"
                % (flash.published_at.strftime("%H:%M"), tag, flash.title[:52])
            )
        if not before:
            print("     （这一小时没有带标签的快讯）")
        print()

    total = hit + miss
    print("共 %d 波：有方向信号 %d 波，对 %d 错 %d" % (len(swings), total, hit, miss), end="")
    if total:
        print("，命中率 %.0f%%" % (hit / total * 100))
    else:
        print()
    print("无信号 %d 波" % blank)
    db.close()


if __name__ == "__main__":
    main()
