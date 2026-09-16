"""基金收藏的增删查。按账号隔离：每个账号有自己的收藏和持仓。

注意区分两类数据：
  * fund_favorites 是账号私有的（收藏、份额、成本价）
  * fund_holdings / fund_navs / fund_stock_quotes 是市场数据，多账号共享
所以取消收藏时不能无条件删掉共享数据，得先确认没有别的账号还在收藏这只基金。
"""

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
    """所有账号收藏过的基金代码，去重。采集任务用这个，与账号无关。"""
    return list(db.scalars(select(FundFavorite.code).distinct()).all())


def list_codes_of(db: Session, user_id: int) -> List[str]:
    return list(
        db.scalars(
            select(FundFavorite.code)
            .where(FundFavorite.user_id == user_id)
            .order_by(FundFavorite.sort_order.asc(), FundFavorite.code.asc())
        ).all()
    )


def list_favorites(db: Session, user_id: int) -> List[FundFavorite]:
    return list(
        db.scalars(
            select(FundFavorite)
            .where(FundFavorite.user_id == user_id)
            .order_by(FundFavorite.sort_order.asc(), FundFavorite.code.asc())
        ).all()
    )


def get_favorite(db: Session, user_id: int, code: str) -> Optional[FundFavorite]:
    return db.scalar(
        select(FundFavorite).where(FundFavorite.user_id == user_id, FundFavorite.code == (code or "").strip())
    )


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


def add_favorite(db: Session, user_id: int, code: str) -> FundFavorite:
    cleaned = normalize_code(code)
    existing = get_favorite(db, user_id, cleaned)
    if existing:
        return existing
    name, fund_type = _lookup_name(cleaned)
    if not name:
        raise ValueError("查不到这只基金，确认下代码是不是对的")
    top = db.scalar(select(func.max(FundFavorite.sort_order)).where(FundFavorite.user_id == user_id)) or 0
    row = FundFavorite(
        user_id=user_id,
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


def set_position(
    db: Session, user_id: int, code: str, shares: Optional[float], cost_price: Optional[float]
) -> FundFavorite:
    """填持仓份额和成本价。两个都留空就是清掉持仓，只保留收藏。"""
    row = get_favorite(db, user_id, code)
    if not row:
        raise KeyError(code)
    if shares is not None and shares < 0:
        raise ValueError("份额不能是负数")
    if cost_price is not None and cost_price < 0:
        raise ValueError("成本价不能是负数")
    if shares is not None and shares > 0 and not cost_price:
        raise ValueError("填了份额也要填成本价，不然算不出盈亏")
    row.shares = round(shares, 4) if shares else None
    row.cost_price = round(cost_price, 4) if cost_price else None
    db.commit()
    db.refresh(row)
    return row


def delete_favorite(db: Session, user_id: int, code: str) -> None:
    row = get_favorite(db, user_id, code)
    if not row:
        raise KeyError(code)
    db.delete(row)
    db.commit()
    # 只有没人再收藏这只基金时，才清掉它的持仓明细和净值 ——
    # 这两张表是共享的，别的账号可能还在用
    still_wanted = db.scalar(
        select(func.count()).select_from(FundFavorite).where(FundFavorite.code == row.code)
    )
    if still_wanted:
        return
    for holding in db.scalars(select(FundHolding).where(FundHolding.fund_code == row.code)).all():
        db.delete(holding)
    nav = db.get(FundNav, row.code)
    if nav:
        db.delete(nav)
    db.commit()
