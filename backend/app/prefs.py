"""页面可改的本地设置，存在数据库里。"""

from sqlalchemy.orm import Session

from .config import settings
from .models import AppSetting
from .timeutil import now_local

BUDGET_KEY = "stock_budget_yuan"
MIN_BUDGET = 1000
MAX_BUDGET = 10_000_000


def get_pref(db: Session, key: str, default: str) -> str:
    row = db.get(AppSetting, key)
    return row.value if row and row.value is not None else default


def set_pref(db: Session, key: str, value: str) -> str:
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value, updated_at=now_local())
        db.add(row)
    else:
        row.value = value
        row.updated_at = now_local()
    db.commit()
    return row.value


def get_budget(db: Session) -> float:
    raw = get_pref(db, BUDGET_KEY, str(int(settings.stock_budget_yuan)))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = settings.stock_budget_yuan
    return max(MIN_BUDGET, min(MAX_BUDGET, value))


def set_budget(db: Session, value: float) -> float:
    cleaned = max(MIN_BUDGET, min(MAX_BUDGET, float(value)))
    set_pref(db, BUDGET_KEY, str(int(round(cleaned))))
    return get_budget(db)
