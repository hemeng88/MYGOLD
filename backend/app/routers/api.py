from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..analysis.fund_estimate import fund_detail, list_funds
from ..analysis.sessions import snapshot as session_snapshot
from ..collectors.service import collect_once, get_curve, get_latest_quote, list_days, list_events
from ..database import get_db
from ..formula import rule_payload
from ..funds import favorites as fund_favorites
from ..funds.collector import prune_stock_quotes, refresh_funds, sync_fund
from ..funds.rankings import DEFAULT_PERIOD, collect_rankings, list_rankings
from ..funds.sources import search_funds
from ..schemas import (
    CollectResult,
    CurveResponse,
    DaySummary,
    FeeRule,
    FundDetailResponse,
    FundFavoriteIn,
    FundFavoriteOut,
    FundListResponse,
    FundPositionIn,
    FundRankRefreshResult,
    FundRankResponse,
    FundRefreshResult,
    FundSearchItem,
    LatestQuote,
    MarketEventOut,
    SessionSnapshot,
)
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


@router.get("/sessions", response_model=SessionSnapshot)
def sessions(db: Session = Depends(get_db)):
    return session_snapshot(db)


@router.get("/funds", response_model=FundListResponse)
def funds(db: Session = Depends(get_db)):
    return list_funds(db)


@router.get("/funds/search", response_model=List[FundSearchItem])
def fund_search(
    q: str = Query(min_length=1, max_length=32, description="基金代码或名称关键字"),
    limit: int = Query(default=12, ge=1, le=30),
    db: Session = Depends(get_db),
):
    try:
        rows = search_funds(q, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="基金搜索失败：%s" % exc) from exc
    owned = set(fund_favorites.list_codes(db))
    return [dict(row, favorited=row["code"] in owned) for row in rows]


@router.get("/funds/rankings", response_model=FundRankResponse)
def fund_rankings(
    period: str = Query(default=DEFAULT_PERIOD, description="周期键，见返回里的 periods"),
    stock_limit: int = Query(default=12, ge=1, le=40),
    db: Session = Depends(get_db),
):
    return list_rankings(db, period=period, stock_limit=stock_limit)


@router.post("/funds/rankings/refresh", response_model=FundRankRefreshResult)
def fund_rankings_refresh(db: Session = Depends(get_db)):
    try:
        return collect_rankings(db)
    except Exception as exc:
        db.rollback()
        return {"ok": False, "periods": 0, "funds": 0, "message": "榜单刷新中断：%s" % exc}


@router.get("/funds/favorites", response_model=List[FundFavoriteOut])
def fund_favorite_list(db: Session = Depends(get_db)):
    return fund_favorites.list_favorites(db)


@router.post("/funds/favorites", response_model=FundFavoriteOut)
def fund_favorite_add(payload: FundFavoriteIn, db: Session = Depends(get_db)):
    try:
        row = fund_favorites.add_favorite(db, payload.code)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 收藏完立刻补一次持仓和报价，不然要等定时任务才看得到估值
    try:
        sync_fund(db, row.code)
    except Exception:
        db.rollback()
    return row


@router.put("/funds/favorites/{code}/position", response_model=FundFavoriteOut)
def fund_position_save(code: str, payload: FundPositionIn, db: Session = Depends(get_db)):
    try:
        return fund_favorites.set_position(db, code, payload.shares, payload.cost_price)
    except KeyError:
        raise HTTPException(status_code=404, detail="没有收藏这只基金")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/funds/favorites/{code}")
def fund_favorite_remove(code: str, db: Session = Depends(get_db)):
    try:
        fund_favorites.delete_favorite(db, code)
    except KeyError:
        raise HTTPException(status_code=404, detail="没有收藏这只基金")
    prune_stock_quotes(db)
    return {"ok": True}


@router.post("/funds/refresh", response_model=FundRefreshResult)
def fund_refresh(
    include_holdings: bool = Query(default=False, description="是否重拉季报持仓，持仓一季度才变一次"),
    db: Session = Depends(get_db),
):
    try:
        return refresh_funds(db, include_holdings=include_holdings)
    except Exception as exc:
        db.rollback()
        return {
            "ok": False,
            "holdings": 0,
            "navs": 0,
            "quotes": 0,
            "message": "基金刷新中断：%s" % exc,
        }


@router.get("/funds/{code}", response_model=FundDetailResponse)
def fund(code: str, db: Session = Depends(get_db)):
    if not fund_favorites.get_favorite(db, code):
        raise HTTPException(status_code=404, detail="这只基金还没收藏")
    return fund_detail(db, code)
