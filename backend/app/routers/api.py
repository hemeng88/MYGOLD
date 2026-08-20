from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..collectors.service import collect_once, get_curve, get_latest_quote, list_days
from ..database import get_db
from ..schemas import CollectResult, CurveResponse, DaySummary, LatestQuote
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
