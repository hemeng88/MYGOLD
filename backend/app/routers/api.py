from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..collectors.service import collect_once, get_curve, get_latest_quote, list_days, list_events
from ..database import get_db
from ..formula import rule_payload
from ..holdings import add_lot, delete_lot, list_holdings
from ..schemas import CollectResult, CurveResponse, DaySummary, FeeRule, GoldLotIn, GoldLotOut, HoldingSummary, LatestQuote, MarketEventOut
from ..timeutil import now_local, trade_date_today

router = APIRouter()


@router.get("/health")
def health():
    return {"ok": True, "time": now_local().isoformat(timespec="seconds"), "today": trade_date_today()}


@router.get("/quote/latest", response_model=LatestQuote)
def latest_quote(db: Session = Depends(get_db)):
    quote = get_latest_quote(db)
    if not quote:
        raise HTTPException(status_code=404, detail="还没有采集到价格，请先触发一次采集")
    return quote


@router.get("/curve", response_model=CurveResponse)
def curve(date: Optional[str] = Query(default=None, description="交易日 YYYY-MM-DD"), db: Session = Depends(get_db)):
    return get_curve(db, date)


@router.get("/days", response_model=List[DaySummary])
def days(db: Session = Depends(get_db)):
    return list_days(db)


@router.post("/collect", response_model=CollectResult)
async def collect(include_chart: bool = True, db: Session = Depends(get_db)):
    try:
        return await collect_once(db, include_chart=include_chart)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail="采集失败：%s" % exc) from exc


@router.get("/rules", response_model=FeeRule)
def rules(buy_price: Optional[float] = Query(default=None), db: Session = Depends(get_db)):
    price = buy_price
    if price is None:
        quote = get_latest_quote(db)
        price = quote.price if quote else None
    return FeeRule(**rule_payload(price))


@router.get("/events", response_model=List[MarketEventOut])
def events(
    date: Optional[str] = Query(default=None, description="交易日 YYYY-MM-DD，缺省为全部"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return list_events(db, date, limit)


@router.get("/holdings", response_model=HoldingSummary)
def holdings(db: Session = Depends(get_db)):
    return list_holdings(db)


@router.post("/holdings/lots", response_model=GoldLotOut)
def create_lot(payload: GoldLotIn, db: Session = Depends(get_db)):
    try:
        return add_lot(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/holdings/lots/{lot_id}")
def remove_lot(lot_id: int, db: Session = Depends(get_db)):
    try:
        delete_lot(db, lot_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="没有这条持仓记录")
    return {"ok": True}
