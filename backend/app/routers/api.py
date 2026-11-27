from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..analysis.fund_estimate import fund_detail, list_funds
from ..auth import login as auth_login
from ..auth import require_auth
from ..misc import countdowns as misc_countdowns
from ..models import User
from ..database import get_db
from ..funds import favorites as fund_favorites
from ..funds.collector import prune_stock_quotes, refresh_funds, sync_fund
from ..funds.sources import search_assets, search_stocks
from ..schemas import (
    CountdownIn,
    CountdownOut,
    FundDetailResponse,
    FundFavoriteIn,
    FundFavoriteOut,
    FundListResponse,
    FundPositionIn,
    FundRefreshResult,
    FundSearchItem,
    LoginIn,
    LoginOut,
    MainboardDetailResponse,
    MainboardRefreshResult,
    MainboardResponse,
    MainboardSearchItem,
    MeOut,
)
from ..stocks import universe as stock_universe
from ..stocks.collector import list_mainboard, mainboard_detail, refresh_mainboard
from ..stocks.signals import SnapshotChanged, get_signals
from ..stocks import holding_analysis, single_stock, portfolio, simulator
from ..stocks.preferences import load_boards, save_boards
from ..schemas import StockBoardPreferenceIn
from ..schemas import StockAIProfileIn, StockAnalysisIn, StockSingleAnalysisIn, StockPortfolioIn, StockPricePreferenceIn, StockSimConfig, StockSimRunIn
from ..stocks.preferences import load_prices, save_prices
from ..schemas import DeepSeekConfigIn
from ..stocks import ai_settings
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
        rows = search_assets(q, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="基金搜索失败：%s" % exc) from exc
    owned = set(fund_favorites.list_codes_of(db, user.id))
    return [dict(row, favorited=row["code"] in owned) for row in rows]


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


@guarded.get("/stocks/search", response_model=List[MainboardSearchItem])
def stocks_search(
    q: str = Query(min_length=1, max_length=32, description="A 股代码或名称关键字"),
    limit: int = Query(default=12, ge=1, le=30),
    _user: User = Depends(require_auth),
):
    """主动搜索全 A 股，不受默认沪深300主板非 ST 样本限制。"""
    try:
        rows = search_stocks(q, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="股票搜索失败：%s" % exc) from exc
    out = []
    for row in rows:
        secid = row["secid"]
        code = secid.partition(".")[2]
        board, eligible, reason = stock_universe.classify(code, row["name"])
        out.append(
            {
                "code": code,
                "name": row["name"],
                "secid": secid,
                "board": board,
                "eligible": eligible,
                "reason": reason,
            }
        )
    return out


@guarded.get("/stocks/mainboard", response_model=MainboardResponse)
def stocks_mainboard(
    period: str = Query(default="3m", description="均价周期：1m / 3m / 6m / ytd / 1y"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_auth),
):
    """新开户可买主板样本：沪深300里的主板，现价对照所选周期均价。"""
    return list_mainboard(db, period)


@guarded.post("/stocks/mainboard/refresh", response_model=MainboardRefreshResult)
def stocks_mainboard_refresh(
    include_klines: bool = Query(default=False, description="是否重拉近一年日线，日线一天变一次"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_auth),
):
    try:
        return refresh_mainboard(db, include_klines=include_klines)
    except Exception as exc:
        db.rollback()
        return {"ok": False, "quotes": 0, "klines": 0, "hs300": 0, "message": "主板样本刷新中断：%s" % exc}


@guarded.get("/stocks/mainboard/{code}", response_model=MainboardDetailResponse)
def stocks_mainboard_detail(
    code: str,
    period: str = Query(default="3m", description="走势周期：1m / 3m / 6m / ytd / 1y"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_auth),
):
    """单只 A 股的周期均值和走势；主动查询不受默认可买样本限制。"""
    cleaned = (code or "").strip()
    if stock_universe.secid_of(cleaned) is None:
        raise HTTPException(status_code=400, detail="股票代码应该是 6 位 A 股代码")
    detail = mainboard_detail(db, cleaned, period)
    if detail is None:
        raise HTTPException(status_code=404, detail="查不到这只股票的足够历史数据")
    return detail


@guarded.get("/misc/countdowns", response_model=List[CountdownOut])
def countdown_list(db: Session = Depends(get_db), user: User = Depends(require_auth)):
    return misc_countdowns.list_countdowns(db, user.id)


@guarded.post("/misc/countdowns", response_model=CountdownOut)
def countdown_add(payload: CountdownIn, db: Session = Depends(get_db), user: User = Depends(require_auth)):
    try:
        return misc_countdowns.add_countdown(db, user.id, payload.model_dump())
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@guarded.put("/misc/countdowns/{item_id}", response_model=CountdownOut)
def countdown_update(
    item_id: int,
    payload: CountdownIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_auth),
):
    try:
        return misc_countdowns.update_countdown(db, user.id, item_id, payload.model_dump())
    except KeyError:
        raise HTTPException(status_code=404, detail="没有这条倒计时")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@guarded.delete("/misc/countdowns/{item_id}")
def countdown_remove(item_id: int, db: Session = Depends(get_db), user: User = Depends(require_auth)):
    try:
        misc_countdowns.delete_countdown(db, user.id, item_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="没有这条倒计时")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@guarded.get("/funds/{code}", response_model=FundDetailResponse)
def fund(code: str, db: Session = Depends(get_db), user: User = Depends(require_auth)):
    if not fund_favorites.get_favorite(db, user.id, code):
        raise HTTPException(status_code=404, detail="这只基金还没收藏")
    return fund_detail(db, user.id, code)


def _holding_favorite(db, user_id, code):
    row = fund_favorites.get_favorite(db, user_id, code)
    if row is None:
        raise HTTPException(status_code=404, detail="没有找到这只收藏的股票。")
    return row


def _holding_snapshot(db, user_id, code, snapshot_id):
    row = _holding_favorite(db, user_id, code)
    try:
        return holding_analysis.saved_preview(user_id, row, snapshot_id)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@guarded.get("/funds/favorites/{code}/holding-analysis")
def holding_preview(code: str, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    row = _holding_favorite(db, user.id, code)
    try:
        snapshot = holding_analysis.create_preview(user.id, row)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return holding_analysis.view(snapshot, ai_settings.analysis_configs(db, user.id)["ai_profiles"])


@guarded.get("/funds/favorites/{code}/holding-analysis/status")
def holding_status(code: str, snapshot_id: str = Query(pattern=r"^[a-f0-9]{64}$"),
                   user: User = Depends(require_auth), db: Session = Depends(get_db)):
    snapshot = _holding_snapshot(db, user.id, code, snapshot_id)
    return holding_analysis.view(snapshot, ai_settings.analysis_configs(db, user.id)["ai_profiles"])


@guarded.post("/funds/favorites/{code}/holding-analysis/analyze")
def review_holding(code: str, selection: StockSingleAnalysisIn, snapshot_id: str = Query(pattern=r"^[a-f0-9]{64}$"),
                   user: User = Depends(require_auth), db: Session = Depends(get_db)):
    snapshot = _holding_snapshot(db, user.id, code, snapshot_id)
    profiles = ai_settings.analysis_configs(db, user.id)["ai_profiles"]
    try:
        selected = ai_settings.select_profiles(profiles, selection.profile_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return holding_analysis.view(snapshot, profiles, selected)


@guarded.get("/stocks/signals")
def stock_signals(user: User = Depends(require_auth), db: Session = Depends(get_db), mode: Literal["intraday", "close"] = "intraday"):
    options = {"mode": mode} if mode != "intraday" else {}
    low, high = load_prices(db, user.id)
    options.update(price_min=low, price_max=high)
    return get_signals(boards=load_boards(db, user.id), **ai_settings.analysis_configs(db, user.id), **options)


@guarded.post("/stocks/signals/refresh")
def stock_signals_refresh(user: User = Depends(require_auth), db: Session = Depends(get_db), mode: Literal["intraday", "close"] = "intraday"):
    options = {"mode": mode} if mode != "intraday" else {}
    low, high = load_prices(db, user.id)
    options.update(price_min=low, price_max=high)
    return get_signals(refresh=True, boards=load_boards(db, user.id), **ai_settings.analysis_configs(db, user.id), **options)


@guarded.post("/stocks/signals/analyze")
def stock_signals_analyze(user: User = Depends(require_auth), db: Session = Depends(get_db),
                          mode: Literal["intraday", "close"] = "intraday", snapshot_id: str = Query(pattern=r"^[a-f0-9]{64}$"),
                          selection: Optional[StockAnalysisIn] = None):
    options = {"mode": mode} if mode != "intraday" else {}
    low, high = load_prices(db, user.id)
    options.update(price_min=low, price_max=high)
    if selection is not None:
        options["requested_codes"] = selection.codes
        if selection.profile_ids is not None:
            options["requested_profile_ids"] = selection.profile_ids
    try:
        return get_signals(analyze=True, requested_snapshot_id=snapshot_id, boards=load_boards(db, user.id),
                           **ai_settings.analysis_configs(db, user.id), **options)
    except SnapshotChanged as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@guarded.get("/stocks/portfolio-study")
def stock_portfolio_status(user: User = Depends(require_auth)):
    return portfolio.status(user.id)


@guarded.get("/stocks/simulator")
def stock_simulator(period: Literal["7", "30", "90", "all"] = "30",
                    user: User = Depends(require_auth), db: Session = Depends(get_db)):
    return simulator.view(db, user.id, period)


@guarded.put("/stocks/simulator/config")
def configure_stock_simulator(payload: StockSimConfig, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    try:
        simulator.save_config(db, user.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@guarded.put("/stocks/simulator/run")
def toggle_stock_simulator(payload: StockSimRunIn, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    try:
        simulator.set_running(db, user.id, payload.running)
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}


@guarded.post("/stocks/portfolio-study", status_code=202)
def stock_portfolio_start(payload: StockPortfolioIn, mode: Literal["intraday", "close"] = "intraday",
                          user: User = Depends(require_auth), db: Session = Depends(get_db)):
    low, high = load_prices(db, user.id)
    snapshot = get_signals(boards=load_boards(db, user.id), mode=mode, price_min=low, price_max=high,
                           for_portfolio=True)
    try:
        return portfolio.start(user.id, snapshot, low, high, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc


@guarded.get("/stocks/single-analysis/{code}")
def single_stock_preview(code: str, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    low, high = load_prices(db, user.id)
    try:
        snapshot = single_stock.create_preview(user.id, code, load_boards(db, user.id), low, high)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    options = ai_settings.analysis_configs(db, user.id)
    return single_stock.view(snapshot, options["ai_config"], profiles=options["ai_profiles"])


def _single_stock_snapshot(user_id, code, snapshot_id):
    try:
        return single_stock.saved_preview(user_id, code, snapshot_id)
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@guarded.get("/stocks/single-analysis/{code}/status")
def single_stock_status(code: str, snapshot_id: str = Query(pattern=r"^[a-f0-9]{64}$"),
                        user: User = Depends(require_auth), db: Session = Depends(get_db)):
    snapshot = _single_stock_snapshot(user.id, code, snapshot_id)
    options = ai_settings.analysis_configs(db, user.id)
    return single_stock.view(snapshot, options["ai_config"], profiles=options["ai_profiles"])


@guarded.post("/stocks/single-analysis/{code}/analyze")
def single_stock_review(code: str, snapshot_id: str = Query(pattern=r"^[a-f0-9]{64}$"),
                        selection: Optional[StockSingleAnalysisIn] = None,
                        user: User = Depends(require_auth), db: Session = Depends(get_db)):
    snapshot = _single_stock_snapshot(user.id, code, snapshot_id)
    low, high = load_prices(db, user.id)
    if (snapshot["allowed_boards"], snapshot["price_min"], snapshot["price_max"]) != (load_boards(db, user.id), low, high):
        raise HTTPException(status_code=409, detail="选股范围已变化，请重新查询股票。")
    options = ai_settings.analysis_configs(db, user.id)
    profiles = options["ai_profiles"]
    try:
        selected = ai_settings.select_profiles(profiles, selection.profile_ids if selection else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return single_stock.view(snapshot, options["ai_config"], profiles=profiles, selected=selected)


@guarded.put("/stocks/signals/preferences")
def stock_signals_preferences(payload: StockBoardPreferenceIn, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    try:
        return {"boards": save_boards(db, user.id, payload.boards)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@guarded.put("/stocks/signals/prices")
def stock_signal_prices(payload: StockPricePreferenceIn, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    try:
        return save_prices(db, user.id, payload.price_min, payload.price_max)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@guarded.get("/settings/deepseek")
@guarded.get("/settings/ai")
def deepseek_config_get(user: User = Depends(require_auth), db: Session = Depends(get_db)):
    return ai_settings.public_status(ai_settings.resolve(db, user.id))


@guarded.put("/settings/deepseek")
@guarded.put("/settings/ai")
def deepseek_config_save(payload: DeepSeekConfigIn, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    try:
        return ai_settings.save(db, user.id, payload.api_key, payload.model, provider=payload.provider,
                                base_url=payload.base_url, json_mode=payload.json_mode, token_field=payload.token_field)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@guarded.delete("/settings/deepseek")
@guarded.delete("/settings/ai")
def deepseek_config_delete(user: User = Depends(require_auth), db: Session = Depends(get_db)):
    return ai_settings.disable(db, user.id)


@guarded.post("/settings/deepseek/test")
@guarded.post("/settings/ai/test")
def deepseek_config_test(user: User = Depends(require_auth), db: Session = Depends(get_db)):
    try:
        return ai_settings.test_connection(ai_settings.resolve(db, user.id), user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@guarded.post("/settings/ai/test-generation")
def model_config_generation_test(user: User = Depends(require_auth), db: Session = Depends(get_db)):
    try:
        return ai_settings.test_generation(ai_settings.resolve(db, user.id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@guarded.get("/settings/ai/profiles")
def list_ai_profiles(user: User = Depends(require_auth), db: Session = Depends(get_db)):
    options = ai_settings.analysis_configs(db, user.id)
    return {"providers": ai_settings.provider_presets(),
            "profiles": [ai_settings.profile_status(profile) for profile in options["ai_profiles"]]}


def _write_ai_profile(db, user_id, payload, profile_id=None):
    try:
        return ai_settings.save_profile(db, user_id, payload, profile_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@guarded.post("/settings/ai/profiles", status_code=201)
def create_ai_profile(payload: StockAIProfileIn, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    return _write_ai_profile(db, user.id, payload)


@guarded.put("/settings/ai/profiles/{profile_id}")
def update_ai_profile(profile_id: str, payload: StockAIProfileIn,
                      user: User = Depends(require_auth), db: Session = Depends(get_db)):
    return _write_ai_profile(db, user.id, payload, profile_id)


@guarded.delete("/settings/ai/profiles/{profile_id}")
def remove_ai_profile(profile_id: str, user: User = Depends(require_auth), db: Session = Depends(get_db)):
    try:
        ai_settings.delete_profile(db, user.id, profile_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@guarded.post("/settings/ai/profiles/{profile_id}/{action}")
def test_ai_profile(profile_id: str, action: Literal["test", "test-generation"],
                    user: User = Depends(require_auth), db: Session = Depends(get_db)):
    try:
        profile = ai_settings.get_profile(db, user.id, profile_id)
        return ai_settings.test_connection(profile, user.id) if action == "test" else ai_settings.test_generation(profile)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


router.include_router(guarded)
