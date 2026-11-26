"""策略候选日记：只记录首次出现，未来数据到来后计算前向事件收益。"""
from sqlalchemy import select, func

from ..models import StrategyObservation
from ..timeutil import now_local
from .research import VERSION, HOLD, net_return
from . import universe


def pending_symbols(db, limit=20, boards=None):
    # 每轮最多额外取20个未完成观察的历史，避免无上限网络请求。
    symbols = list(db.scalars(select(StrategyObservation.symbol)
                .where(StrategyObservation.version == VERSION, StrategyObservation.net_pct.is_(None))
                .group_by(StrategyObservation.symbol)
                .order_by(func.min(StrategyObservation.checked_at), StrategyObservation.symbol)).all())
    return [symbol for symbol in symbols if not boards or universe.board_of(symbol[2:]) in boards][:limit]


def update(db, snapshot, histories):
    today = now_local().date().isoformat()
    rows = list(db.scalars(select(StrategyObservation).where(StrategyObservation.version == VERSION)).all())
    existing = {(row.signal_date, row.code, row.strategy) for row in rows}
    # 只有今日完整扫描记录；重启或手动重扫不改写原始价格。
    if snapshot.get("complete") and snapshot.get("trade_date") == today:
        for item in snapshot["items"]:
            for strategy in item.get("strategies", []):
                key = (today, item["code"], strategy)
                if key in existing:
                    continue
                row = StrategyObservation(version=VERSION, signal_date=today, code=item["code"],
                      symbol=item["symbol"], strategy=strategy, reference_price=item["price"], created_at=now_local())
                db.add(row)
                rows.append(row)
                existing.add(key)
    for row in rows:
        if row.net_pct is not None:
            continue
        bars = histories.get(row.symbol) or []
        if row.symbol in histories:
            row.checked_at = now_local()
        future = [(day, price) for day, price in bars if row.signal_date < day < today]
        calendar = [day for day, _ in histories.get("sh000300", []) if row.signal_date < day < today]
        if not calendar or not future:
            continue
        # 不以复牌后的第一根替代信号次日；缺失时留待人工检查，不虚构成交。
        if future[0][0] != calendar[0]:
            continue
        row.entry_date = future[0][0]
        if len(calendar) > HOLD and len(future) > HOLD and [day for day, _ in future[:HOLD + 1]] == calendar[:HOLD + 1]:
            row.exit_date = future[HOLD][0]
            row.net_pct = round(net_return(future[0][1], future[HOLD][1]) * 100, 3)
    db.commit()
    boards = snapshot.get("allowed_boards")
    rows = [row for row in rows if not boards or universe.board_of(row.code) in boards]
    completed = [row for row in rows if row.net_pct is not None]
    return {"recorded": len(rows), "completed": len(completed), "pending": len(rows) - len(completed),
            "avg_net_pct": round(sum(row.net_pct for row in completed) / len(completed), 3) if completed else None,
            "note": "真实记录后才开始跟踪：次一交易日收盘假设入场，五交易日后收盘退出；非真实成交，多个样本可能相关。"}
