from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class LatestQuote(BaseModel):
    price: float
    yesterday_price: Optional[float] = None
    change_amt: Optional[float] = None
    change_rate: Optional[str] = None
    source_time: Optional[datetime] = None
    collected_at: Optional[datetime] = None
    source: str
    trade_date: str
    london_usd: Optional[float] = None
    london_prev: Optional[float] = None
    london_change_amt: Optional[float] = None
    london_change_rate: Optional[float] = None
    london_source: Optional[str] = None
    usdcny: Optional[float] = None
    usdcny_prev: Optional[float] = None
    usdcny_change_amt: Optional[float] = None
    usdcny_change_rate: Optional[float] = None
    usdcny_source: Optional[str] = None
    troy_ounce_grams: Optional[float] = None
    london_cny_gram: Optional[float] = None
    zheshang_usd_oz: Optional[float] = None
    premium_cny: Optional[float] = None
    premium_pct: Optional[float] = None


class CurvePointOut(BaseModel):
    t: int
    p: float
    time: str


class DaySummary(BaseModel):
    date: str
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    prev_close: Optional[float] = None
    change_amt: Optional[float] = None
    change_rate: Optional[float] = None
    point_count: int = 0
    first_ts: Optional[int] = None
    last_ts: Optional[int] = None
    updated_at: Optional[datetime] = None


class CurveResponse(BaseModel):
    date: str
    summary: Optional[DaySummary] = None
    points: List[CurvePointOut]


class CollectResult(BaseModel):
    ok: bool
    message: str
    tick: Optional[LatestQuote] = None
    curve_points_upserted: int = 0
    event_recorded: bool = False


class FeeRule(BaseModel):
    sell_fee_rate: float
    breakeven_rate: float
    breakeven_rate_pct: float
    formula: str
    note: str
    watch_window_seconds: int
    persist_checks: int
    tick_interval_seconds: int
    example_buy_price: Optional[float] = None
    example_breakeven_sell: Optional[float] = None
    example_needed_rise: Optional[float] = None


class MarketEventOut(BaseModel):
    id: int
    trade_date: str
    triggered_at: datetime
    direction: str
    start_price: float
    end_price: float
    change_amt: float
    change_rate: float
    threshold_rate: float
    window_seconds: int
    window_started_at: Optional[datetime] = None
    ts: Optional[int] = None
    headline: str
    source: Optional[str] = None
    url: Optional[str] = None
    summary: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class SessionRange(BaseModel):
    start: str
    end: str
    start_min: int
    end_min: int


class SessionExchange(BaseModel):
    id: str
    name: str
    region: str
    timezone: str
    source: str
    open: bool
    weekend: bool
    ranges: List[SessionRange] = Field(default_factory=list)
    start: Optional[str] = None
    impact_abs_pct: Optional[float] = None
    hot: bool = False
    hot_rank: Optional[int] = None


class SessionBand(BaseModel):
    id: str
    label: str
    color: str


class SessionHour(BaseModel):
    hour: int
    label: str
    samples: int
    mean_pct: Optional[float] = None
    abs_pct: Optional[float] = None
    win_rate: Optional[int] = None


class SessionSnapshot(BaseModel):
    as_of: str
    timezone: str
    clock: str
    clock_min: int
    band: str
    band_label: str
    open_count: int
    open_names: List[str] = Field(default_factory=list)
    exchanges: List[SessionExchange] = Field(default_factory=list)
    bands: List[SessionBand] = Field(default_factory=list)
    hour_profile: List[SessionHour] = Field(default_factory=list)
    hour_abs_pct: Optional[float] = None
    hour_mean_pct: Optional[float] = None
    hour_win_rate: Optional[int] = None
    hour_samples: int = 0
    hour_vol_rank_pct: Optional[int] = None
    profile_days: int = 0
    note: str = ""


class FundHoldingItem(BaseModel):
    secid: str
    code: str
    name: Optional[str] = None
    market: Optional[str] = None
    weight_pct: float
    rank: Optional[int] = None
    price: Optional[float] = None
    change_pct: Optional[float] = None
    contrib_pct: Optional[float] = None
    quoted: bool = False


class FundItem(BaseModel):
    code: str
    name: str
    fund_type: Optional[str] = None
    nav: Optional[float] = None
    nav_date: Optional[str] = None
    nav_chg_pct: Optional[float] = None
    # 货币基金：净值恒为 1，收益看万份收益
    is_cash_fund: bool = False
    yield_10k: Optional[float] = None
    # 手填持仓，用来算盈亏金额
    shares: Optional[float] = None
    cost_price: Optional[float] = None
    cost: Optional[float] = None
    nav_value: Optional[float] = None
    estimate_value: Optional[float] = None
    today_pnl: Optional[float] = None
    total_pnl: Optional[float] = None
    total_pnl_pct: Optional[float] = None
    holdings_count: int = 0
    quoted_count: int = 0
    disclosed_pct: Optional[float] = None
    covered_pct: Optional[float] = None
    estimate_pct: Optional[float] = None
    conservative_pct: Optional[float] = None
    estimate_nav: Optional[float] = None
    report_date: Optional[str] = None
    report_label: Optional[str] = None
    report_age_days: Optional[int] = None
    stale: bool = False
    confidence: str = "low"
    lead_name: Optional[str] = None
    lead_contrib_pct: Optional[float] = None
    drag_name: Optional[str] = None
    drag_contrib_pct: Optional[float] = None
    as_of: Optional[datetime] = None
    ready: bool = False
    message: Optional[str] = None


class FundListResponse(BaseModel):
    session: str
    items: List[FundItem] = Field(default_factory=list)


class FundDetailResponse(BaseModel):
    ready: bool = False
    message: Optional[str] = None
    session: Optional[str] = None
    fund: Optional[FundItem] = None
    holdings: List[FundHoldingItem] = Field(default_factory=list)


class FundFavoriteIn(BaseModel):
    code: str


class FundFavoriteOut(BaseModel):
    code: str
    name: str
    fund_type: Optional[str] = None
    shares: Optional[float] = None
    cost_price: Optional[float] = None
    added_at: datetime


class FundPositionIn(BaseModel):
    """份额和成本价，都传 null 表示清空持仓，只保留收藏。"""

    shares: Optional[float] = None
    cost_price: Optional[float] = None


class FundSearchItem(BaseModel):
    code: str
    name: str
    fund_type: Optional[str] = None
    nav: Optional[float] = None
    nav_date: Optional[str] = None
    favorited: bool = False


class FundRefreshResult(BaseModel):
    ok: bool
    holdings: int = 0
    navs: int = 0
    quotes: int = 0
    message: str


class FundRankPeriod(BaseModel):
    key: str
    label: str


class FundRankFund(BaseModel):
    rank: int
    code: str
    name: str
    return_pct: float
    nav: Optional[float] = None
    nav_date: Optional[str] = None


class FundRankStockItem(BaseModel):
    code: str
    name: Optional[str] = None
    fund_count: int
    weight_sum: float


class FundRankResponse(BaseModel):
    period: str
    period_label: Optional[str] = None
    periods: List[FundRankPeriod] = Field(default_factory=list)
    as_of: Optional[datetime] = None
    funds: List[FundRankFund] = Field(default_factory=list)
    hot_stocks: List[FundRankStockItem] = Field(default_factory=list)
    message: Optional[str] = None


class FundRankRefreshResult(BaseModel):
    ok: bool
    periods: int = 0
    funds: int = 0
    message: str
