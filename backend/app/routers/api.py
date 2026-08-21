from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..analysis.advice import build_advice
from ..analysis.attribution import compute_attribution
from ..analysis.refresh import refresh_attribution_data
from ..analysis.sessions import snapshot as session_snapshot
from ..analysis.stock_advice import build_stock_advice, list_stocks, stock_detail
from ..collectors.service import collect_once, get_curve, get_latest_quote, list_days, list_events
from ..database import get_db
from ..formula import rule_payload
from ..holdings import add_lot, delete_lot, list_holdings
from ..schemas import (
    AdviceResponse,
    AttributionResponse,
    CollectResult,
    CurveResponse,
    DaySummary,
    FeeRule,
    GoldLotIn,
    GoldLotOut,
    HoldingSummary,
    LatestQuote,
    MarketEventOut,
    RefreshResult,
    SessionSnapshot,
    StockAdviceResponse,
    StockDetailResponse,
    StockListResponse,
    StockRefreshResult,
    StockSettings,
)
from ..prefs import get_budget, set_budget
from ..stocks.collector import refresh_stocks
from ..stocks.universe import meta_of
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


@router.get("/advice", response_model=AdviceResponse)
def advice(db: Session = Depends(get_db)):
    return build_advice(db)


@router.get("/sessions", response_model=SessionSnapshot)
def sessions(db: Session = Depends(get_db)):
    return session_snapshot(db)


@router.get("/analysis/weights", response_model=AttributionResponse)
def analysis_weights(
    window_days: int = Query(default=180, ge=30, le=720, description="回看天数"),
    threshold: Optional[float] = Query(default=None, ge=0.1, le=5.0, description="显著波动阈值 %"),
    db: Session = Depends(get_db),
):
    return compute_attribution(db, window_days=window_days, threshold=threshold)


@router.post("/analysis/refresh", response_model=RefreshResult)
async def analysis_refresh(
    window_days: int = Query(default=180, ge=30, le=720),
    with_narrative: bool = Query(default=True, description="是否给显著波动日补叙事快讯"),
    db: Session = Depends(get_db),
):
    try:
        return await refresh_attribution_data(db, window_days=window_days, with_narrative=with_narrative)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail="归因数据刷新失败：%s" % exc) from exc


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


@router.get("/stocks", response_model=StockListResponse)
def stocks(db: Session = Depends(get_db)):
    return list_stocks(db)


@router.get("/stocks/settings", response_model=StockSettings)
def stock_settings(db: Session = Depends(get_db)):
    return {"budget": get_budget(db)}


@router.put("/stocks/settings", response_model=StockSettings)
def update_stock_settings(payload: StockSettings, db: Session = Depends(get_db)):
    return {"budget": set_budget(db, payload.budget)}


@router.get("/stocks/{code}", response_model=StockDetailResponse)
def stock(code: str, db: Session = Depends(get_db)):
    if not meta_of(code):
        raise HTTPException(status_code=404, detail="不在当前观察池里")
    return stock_detail(db, code)


@router.get("/stocks/{code}/advice", response_model=StockAdviceResponse)
def stock_advice(code: str, db: Session = Depends(get_db)):
    if not meta_of(code):
        raise HTTPException(status_code=404, detail="不在当前观察池里")
    return build_stock_advice(db, code)


@router.post("/stocks/refresh", response_model=StockRefreshResult)
async def stock_refresh(include_bars: bool = True, db: Session = Depends(get_db)):
    try:
        return await refresh_stocks(db, include_bars=include_bars)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail="股票数据刷新失败：%s" % exc) from exc
