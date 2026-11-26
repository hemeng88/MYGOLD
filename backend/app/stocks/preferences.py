import json

from ..models import StockResearchPreference

BOARDS = ["主板", "创业板", "科创板", "北交所"]


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
