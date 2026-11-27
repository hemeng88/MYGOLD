import json
from copy import deepcopy
from datetime import date

from sqlalchemy import select

from ..models import StockCloseWatchlist, StockCloseArchive
from .preferences import scope_key


def _raw(snapshot):
    result = deepcopy(snapshot)
    result.pop("history_context", None)
    for item in result.get("items", []):
        item.pop("close_history", None)
    return result


def _archive(db, scope, snapshot):
    row = db.scalar(select(StockCloseArchive).where(
        StockCloseArchive.scope == scope, StockCloseArchive.trade_date == snapshot["trade_date"]))
    if row is None:
        row = StockCloseArchive(scope=scope, trade_date=snapshot["trade_date"])
        db.add(row)
    elif json.loads(row.snapshot_json).get("fetched_at", "") > snapshot.get("fetched_at", ""):
        return
    row.snapshot_json = json.dumps(_raw(snapshot), ensure_ascii=False, allow_nan=False)


def _import_latest(db, boards, price_min=0, price_max=None):
    row = db.get(StockCloseWatchlist, scope_key(boards, price_min, price_max))
    if row:
        saved = json.loads(row.snapshot_json)
        if saved.get("complete") and saved.get("close_ready"):
            _archive(db, row.scope, saved)
            db.commit()


def load(db, boards, price_min=0, price_max=None):
    row = db.get(StockCloseWatchlist, scope_key(boards, price_min, price_max))
    if row is None:
        return None
    result = json.loads(row.snapshot_json)
    attach_history(db, result)
    return result


def save(db, snapshot):
    if not snapshot.get("complete") or not snapshot.get("close_ready"):
        raise ValueError("收盘行情尚未完整，不保存观察池")
    scope = scope_key(snapshot["allowed_boards"], snapshot.get("price_min", 0), snapshot.get("price_max"))
    date.fromisoformat(snapshot["trade_date"])
    _import_latest(db, snapshot["allowed_boards"], snapshot.get("price_min", 0), snapshot.get("price_max"))
    _archive(db, scope, snapshot)
    row = db.get(StockCloseWatchlist, scope)
    if row is not None and (row.trade_date > snapshot["trade_date"] or
                            (row.trade_date == snapshot["trade_date"] and
                             json.loads(row.snapshot_json).get("fetched_at", "") > snapshot.get("fetched_at", ""))):
        db.commit()
        return
    if row is None:
        row = StockCloseWatchlist(scope=scope)
        db.add(row)
    row.trade_date = snapshot["trade_date"]
    row.snapshot_json = json.dumps(_raw(snapshot), ensure_ascii=False, allow_nan=False)
    db.commit()


def attach_history(db, snapshot):
    """严格只读信号基准日之前的归档，不用当天或未来的收盘数据。"""
    boards = snapshot["allowed_boards"]
    _import_latest(db, boards, snapshot.get("price_min", 0), snapshot.get("price_max"))
    as_of = snapshot.get("trade_date")
    rows = list(db.scalars(select(StockCloseArchive).where(
        StockCloseArchive.scope == scope_key(boards, snapshot.get("price_min", 0), snapshot.get("price_max")), StockCloseArchive.trade_date < (as_of or "")
    ).order_by(StockCloseArchive.trade_date.desc()).limit(20)).all())
    dates = [row.trade_date for row in rows]
    archives = [(row.trade_date, json.loads(row.snapshot_json)) for row in rows]
    for item in snapshot.get("items", []):
        records = []
        consecutive = 0
        streak = True
        for trade_date, saved in archives:
            prior = next((entry for entry in saved.get("items", []) if entry.get("code") == item["code"]), None)
            if prior is None:
                streak = False
                continue
            if streak:
                consecutive += 1
            factor = prior.get("factors") or {}
            records.append({"trade_date": trade_date, "price": prior.get("price"),
                            "change_pct": prior.get("change_pct"), "amount": prior.get("amount"),
                            "turnover_pct": prior.get("turnover_pct"), "strategies": prior.get("strategy_labels", []),
                            "fundamentals": {key: (factor.get("fundamentals") or {}).get(key)
                                             for key in ("status", "report_date", "roe_pct", "revenue_yoy_pct", "profit_yoy_pct")},
                            "industry": {key: (factor.get("industry") or {}).get(key)
                                         for key in ("name", "status", "change_pct", "relative_pct", "method")},
                            "market_status": ((saved.get("factor_context") or {}).get("market") or {}).get("status")})
        item["close_history"] = {"appearances": len(records), "consecutive_archives": consecutive,
                                 "records": records}
    snapshot["history_context"] = {
        "status": "available" if rows else "empty", "as_of": as_of, "archive_days": len(rows),
        "ai_detail_limit_per_stock": 5,
        "dates": dates, "source": "服务器每日收盘候选归档（相同板块范围）",
        "note": "仅取基准日前最近20次成功归档；不是完整交易日序列，未归档日期未补造。只保存当日入选候选，未入选不等于股票没有交易。连续次数指连续归档批次，不代表连续交易日。收盘价格未经复权，不得直接据此计算跨除权日收益；这些记录是AI参考资料，不代表策略已验证。",
    }
