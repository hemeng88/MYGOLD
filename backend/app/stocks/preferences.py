import json
import math

from ..models import StockResearchPreference

BOARDS = ["主板", "创业板", "科创板", "北交所"]


def price_range(low=0, high=None):
    low = round(float(low or 0), 2)
    high = round(float(high), 2) if high is not None else None
    if not math.isfinite(low) or low < 0 or (high is not None and (not math.isfinite(high) or high <= 0 or high < low)):
        raise ValueError("请输入有效股价区间，最高价不能低于最低价")
    return round(low, 2), round(high, 2) if high is not None else None


def scope_key(boards, low=0, high=None):
    low, high = price_range(low, high)
    compact = lambda value: format(value, ".2f").rstrip("0").rstrip(".")
    return ",".join(boards) + ("|price=%s:%s" % (compact(low), compact(high) if high is not None else "*") if low or high is not None else "")


def parse_scope(value):
    base, _, prices = value.partition("|price=")
    boards = normalize_boards(base.split(","))
    if not prices:
        return boards, 0, None
    low, high = prices.split(":")
    return boards, *price_range(low, None if high == "*" else high)


def load_prices(db, user_id):
    row = db.get(StockResearchPreference, user_id)
    return price_range(row.price_min, row.price_max) if row else (0, 50)


def save_prices(db, user_id, low, high):
    low, high = price_range(low, high)
    row = db.get(StockResearchPreference, user_id)
    if row is None:
        row = StockResearchPreference(user_id=user_id, boards_json=json.dumps(["主板"]))
        db.add(row)
    row.price_min, row.price_max = low, high
    db.commit()
    return {"price_min": low, "price_max": high}


def normalize_boards(boards=None):
    if boards is None:
        return ["主板"]
    if not boards or any(board not in BOARDS for board in boards):
        raise ValueError("请至少选择一个有效板块")
    return [board for board in BOARDS if board in boards]


def load_boards(db, user_id):
    row = db.get(StockResearchPreference, user_id)
    return normalize_boards(json.loads(row.boards_json)) if row else ["主板"]


def save_boards(db, user_id, boards):
    selected = normalize_boards(boards)
    row = db.get(StockResearchPreference, user_id)
    if row is None:
        row = StockResearchPreference(user_id=user_id)
        db.add(row)
    row.boards_json = json.dumps(selected, ensure_ascii=False)
    db.commit()
    return selected
