"""基金收藏的增删查。单用户，没有 user_id。"""

from __future__ import annotations

import re
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import FundFavorite, FundHolding, FundNav
from ..timeutil import now_local
from .sources import fetch_fund_info, search_funds

_CODE = re.compile(r"^\d{6}$")


def normalize_code(code: str) -> str:
    cleaned = (code or "").strip()
    if not _CODE.match(cleaned):
        raise ValueError("基金代码应该是 6 位数字")
    return cleaned


def list_codes(db: Session) -> List[str]:
    return list(
        db.scalars(
            select(FundFavorite.code).order_by(FundFavorite.sort_order.asc(), FundFavorite.code.asc())
        ).all()
    )


def list_favorites(db: Session) -> List[FundFavorite]:
    return list(
        db.scalars(
            select(FundFavorite).order_by(FundFavorite.sort_order.asc(), FundFavorite.code.asc())
        ).all()
    )


def get_favorite(db: Session, code: str) -> Optional[FundFavorite]:
    return db.get(FundFavorite, code)


def _lookup_name(code: str) -> tuple[Optional[str], Optional[str]]:
    """搜索接口同时给名称和基金类型，取不到再退回净值接口只拿名称。"""
    try:
        for row in search_funds(code, limit=5):
            if row["code"] == code and row.get("name"):
                return row["name"], row.get("fund_type")
    except Exception:
        pass
    try:
        for row in fetch_fund_info([code]):
            if row["code"] == code and row.get("name"):
                return row["name"], None
    except Exception:
        pass
    return None, None


def add_favorite(db: Session, code: str) -> FundFavorite:
    cleaned = normalize_code(code)
    existing = db.get(FundFavorite, cleaned)
    if existing:
        return existing
    name, fund_type = _lookup_name(cleaned)
    if not name:
        raise ValueError("查不到这只基金，确认下代码是不是对的")
    top = db.scalar(select(func.max(FundFavorite.sort_order))) or 0
    row = FundFavorite(
        code=cleaned,
        name=name,
        fund_type=fund_type,
        sort_order=int(top) + 1,
        added_at=now_local(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_favorite(db: Session, code: str) -> None:
    row = db.get(FundFavorite, code)
    if not row:
        raise KeyError(code)
    # 持仓和净值跟着收藏一起清掉，免得留一堆孤儿行
    for holding in db.scalars(select(FundHolding).where(FundHolding.fund_code == code)).all():
        db.delete(holding)
    nav = db.get(FundNav, code)
    if nav:
        db.delete(nav)
    db.delete(row)
    db.commit()
