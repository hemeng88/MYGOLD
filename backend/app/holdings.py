from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .collectors.service import get_latest_quote
from .config import settings
from .formula import breakeven_sell_price, needed_rise_amount
from .models import GoldLot
from .schemas import GoldLotIn, GoldLotOut, HoldingSummary
from .timeutil import now_local, trade_date_today


def _lot_out(row: GoldLot) -> GoldLotOut:
    return GoldLotOut(
        id=row.id,
        grams=row.grams,
        buy_price=row.buy_price,
        bought_at=row.bought_at,
        note=row.note,
        cost=round(row.grams * row.buy_price, 2),
        created_at=row.created_at,
    )


def _validate(payload: GoldLotIn) -> None:
    if payload.grams <= 0:
        raise ValueError("克数必须大于 0")
    if payload.buy_price <= 0:
        raise ValueError("买入价必须大于 0")
    try:
        datetime.strptime(payload.bought_at, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("买入日期格式应为 YYYY-MM-DD") from exc


def list_holdings(db: Session) -> HoldingSummary:
    lots = db.scalars(select(GoldLot).order_by(GoldLot.bought_at.desc(), GoldLot.id.desc())).all()
    total_grams = round(sum(row.grams for row in lots), 4)
    total_cost = round(sum(row.grams * row.buy_price for row in lots), 2)
    avg_cost = round(total_cost / total_grams, 2) if total_grams else None
    quote = get_latest_quote(db)
    current = quote.price if quote else None
    market_value = round(total_grams * current, 2) if current and total_grams else None
    unrealized = round(market_value - total_cost, 2) if market_value is not None else None
    net_if_sell = (
        round(market_value * (1.0 - settings.sell_fee_rate) - total_cost, 2)
        if market_value is not None
        else None
    )
    return HoldingSummary(
        lots=[_lot_out(row) for row in lots],
        total_grams=total_grams,
        avg_cost=avg_cost,
        total_cost=total_cost,
        current_price=current,
        market_value=market_value,
        unrealized_pnl=unrealized,
        net_if_sell_now=net_if_sell,
        breakeven_sell=breakeven_sell_price(avg_cost) if avg_cost else None,
        needed_rise=needed_rise_amount(avg_cost) if avg_cost else None,
        sell_fee_rate=settings.sell_fee_rate,
    )


def add_lot(db: Session, payload: GoldLotIn) -> GoldLotOut:
    _validate(payload)
    row = GoldLot(
        grams=round(payload.grams, 4),
        buy_price=round(payload.buy_price, 2),
        bought_at=payload.bought_at or trade_date_today(),
        note=(payload.note or "").strip() or None,
        created_at=now_local(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _lot_out(row)


def delete_lot(db: Session, lot_id: int) -> None:
    row = db.get(GoldLot, lot_id)
    if not row:
        raise KeyError(lot_id)
    db.delete(row)
    db.commit()
