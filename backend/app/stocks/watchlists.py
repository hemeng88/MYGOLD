import json

from ..models import StockCloseWatchlist


def load(db, boards):
    row = db.get(StockCloseWatchlist, ",".join(boards))
    if row is None:
        return None
    return json.loads(row.snapshot_json)


def save(db, snapshot):
    if not snapshot.get("complete") or not snapshot.get("close_ready"):
        raise ValueError("收盘行情尚未完整，不保存观察池")
    scope = ",".join(snapshot["allowed_boards"])
    row = db.get(StockCloseWatchlist, scope)
    if row is not None and row.trade_date > snapshot["trade_date"]:
        return
    if row is None:
        row = StockCloseWatchlist(scope=scope)
        db.add(row)
    row.trade_date = snapshot["trade_date"]
    row.snapshot_json = json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
    db.commit()
