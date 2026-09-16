from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..analysis.fund_estimate import fund_detail, list_funds
from ..auth import login as auth_login
from ..auth import require_auth
from ..models import User
from ..database import get_db
from ..funds import favorites as fund_favorites
from ..funds.collector import prune_stock_quotes, refresh_funds, sync_fund
from ..funds.rankings import DEFAULT_PERIOD, collect_rankings, list_rankings
from ..funds.sources import search_funds
from ..schemas import (
    FundDetailResponse,
    FundFavoriteIn,
    FundFavoriteOut,
    FundListResponse,
    FundPositionIn,
    FundRankRefreshResult,
    FundRankResponse,
    FundRefreshResult,
    FundSearchItem,
    LoginIn,
    LoginOut,
    MeOut,
)
from ..timeutil import now_local, trade_date_today

router = APIRouter()

# 基金相关全部要登录。挂在子路由上，省得每个接口单独写一遍依赖。
# /api/health 和 /api/auth/login 必须留在免鉴权的 router 上：
# 前者是 docker healthcheck 在打，加了鉴权容器会一直 unhealthy。
guarded = APIRouter()


@router.get("/health")
def health():
    return {"ok": True, "time": now_local().isoformat(timespec="seconds"), "today": trade_date_today()}


@router.post("/auth/login", response_model=LoginOut)
def auth_login_route(payload: LoginIn, db: Session = Depends(get_db)):
    try:
        token, username = auth_login(db, payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"token": token, "username": username}


@router.get("/auth/me", response_model=MeOut)
def auth_me(user: User = Depends(require_auth)):
    """前端启动时拿本地令牌来问一下还有效没，有效就不用再登录。"""
    return {"username": user.username}


@guarded.get("/funds", response_model=FundListResponse)
def funds(db: Session = Depends(get_db), user: User = Depends(require_auth)):
    return list_funds(db, user.id)


@guarded.get("/funds/search", response_model=List[FundSearchItem])
def fund_search(
    q: str = Query(min_length=1, max_length=32, description="基金代码或名称关键字"),
    limit: int = Query(default=12, ge=1, le=30),
    db: Session = Depends(get_db),
    user: User = Depends(require_auth),
):
    try:
        rows = search_funds(q, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="基金搜索失败：%s" % exc) from exc
    owned = set(fund_favorites.list_codes_of(db, user.id))
    return [dict(row, favorited=row["code"] in owned) for row in rows]


@guarded.get("/funds/rankings", response_model=FundRankResponse)
def fund_rankings(
    period: str = Query(default=DEFAULT_PERIOD, description="周期键，见返回里的 periods"),
    stock_limit: int = Query(default=12, ge=1, le=40),
    holder_limit: int = Query(default=5, ge=1, le=10, description="押注最重的基金取前几名"),
    fund_limit: int = Query(default=10, ge=1, le=50, description="涨幅榜列前几名，计算仍用全部"),
    sort: str = Query(default="score", pattern="^(score|consensus)$", description="score 按主线得分，consensus 按抱团度"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_auth),
):
    return list_rankings(
        db,
        period=period,
        stock_limit=stock_limit,
        holder_limit=holder_limit,
        fund_limit=fund_limit,
        sort=sort,
    )


@guarded.post("/funds/rankings/refresh", response_model=FundRankRefreshResult)
def fund_rankings_refresh(db: Session = Depends(get_db), _user: User = Depends(require_auth)):
    try:
        return collect_rankings(db)
    except Exception as exc:
        db.rollback()
        return {"ok": False, "periods": 0, "funds": 0, "message": "榜单刷新中断：%s" % exc}


@guarded.get("/funds/favorites", response_model=List[FundFavoriteOut])
def fund_favorite_list(db: Session = Depends(get_db), user: User = Depends(require_auth)):
    return fund_favorites.list_favorites(db, user.id)


@guarded.post("/funds/favorites", response_model=FundFavoriteOut)
def fund_favorite_add(payload: FundFavoriteIn, db: Session = Depends(get_db), user: User = Depends(require_auth)):
    try:
        row = fund_favorites.add_favorite(db, user.id, payload.code)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 收藏完立刻补一次持仓和报价，不然要等定时任务才看得到估值
    try:
        sync_fund(db, row.code)
    except Exception:
        db.rollback()
    return row


@guarded.put("/funds/favorites/{code}/position", response_model=FundFavoriteOut)
def fund_position_save(code: str, payload: FundPositionIn, db: Session = Depends(get_db), user: User = Depends(require_auth)):
    try:
        return fund_favorites.set_position(db, user.id, code, payload.shares, payload.cost_price)
    except KeyError:
        raise HTTPException(status_code=404, detail="没有收藏这只基金")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@guarded.delete("/funds/favorites/{code}")
def fund_favorite_remove(code: str, db: Session = Depends(get_db), user: User = Depends(require_auth)):
    try:
        fund_favorites.delete_favorite(db, user.id, code)
    except KeyError:
        raise HTTPException(status_code=404, detail="没有收藏这只基金")
    prune_stock_quotes(db)
    return {"ok": True}


@guarded.post("/funds/refresh", response_model=FundRefreshResult)
def fund_refresh(
    include_holdings: bool = Query(default=False, description="是否重拉季报持仓，持仓一季度才变一次"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_auth),
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


@guarded.get("/funds/{code}", response_model=FundDetailResponse)
def fund(code: str, db: Session = Depends(get_db), user: User = Depends(require_auth)):
    if not fund_favorites.get_favorite(db, user.id, code):
        raise HTTPException(status_code=404, detail="这只基金还没收藏")
    return fund_detail(db, user.id, code)


router.include_router(guarded)
