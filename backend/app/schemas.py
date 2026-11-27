from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, SecretStr


class DeepSeekConfigIn(BaseModel):
    api_key: Optional[SecretStr] = None
    model: Optional[str] = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_./:-]+$")
    provider: Optional[str] = Field(default=None, max_length=16)
    base_url: Optional[str] = Field(default=None, max_length=512)
    json_mode: Optional[str] = Field(default=None, max_length=16)
    token_field: Optional[str] = Field(default=None, max_length=32)


class StockBoardPreferenceIn(BaseModel):
    boards: List[str] = Field(min_length=1, max_length=4)


class StockPricePreferenceIn(BaseModel):
    price_min: float = Field(default=0, ge=0, le=100000, allow_inf_nan=False)
    price_max: Optional[float] = Field(default=50, gt=0, le=100000, allow_inf_nan=False)


class StockAnalysisIn(BaseModel):
    codes: List[str] = Field(min_length=1, max_length=20)


class StockPortfolioIn(BaseModel):
    starting_cash: float = Field(default=20000, ge=1000, le=10000000)
    max_positions: int = Field(default=4, ge=1, le=20)
    max_position_pct: float = Field(default=25, ge=5, le=100)
    commission_pct: float = Field(default=0.03, ge=0, le=1)
    min_commission: float = Field(default=5, ge=0, le=100)
    slippage_pct: float = Field(default=0.05, ge=0, le=2)


class StockSimConfig(StockPortfolioIn):
    strategies: List[Literal["trend", "pullback", "low_vol"]] = Field(default_factory=lambda: ["trend", "pullback", "low_vol"], min_length=1, max_length=3)
    price_min: float = Field(default=0, ge=0, lt=100000)
    price_max: Optional[float] = Field(default=50, gt=0, le=100000)
    hold_days: int = Field(default=5, ge=1, le=60)
    stop_loss_pct: float = Field(default=5, ge=0, le=50)
    take_profit_pct: float = Field(default=10, ge=0, le=100)
    max_drawdown_pct: float = Field(default=15, ge=0, le=100)
    require_factors: bool = False


class StockSimRunIn(BaseModel):
    running: bool


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
    asset_type: str = "fund"
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
    # 最新净值日已经追上报价所属交易日，这段涨跌已计入净值，不再给估算
    settled: bool = False
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
    asset_type: str = "fund"
    secid: Optional[str] = None
    market: Optional[str] = None
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
    asset_type: str = "fund"
    secid: Optional[str] = None
    market: Optional[str] = None


class FundRefreshResult(BaseModel):
    ok: bool
    holdings: int = 0
    navs: int = 0
    quotes: int = 0
    message: str


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    token: str
    username: str


class MeOut(BaseModel):
    username: str


class MainboardSearchItem(BaseModel):
    code: str
    name: str
    secid: str
    board: str
    eligible: bool
    reason: Optional[str] = None


class MainboardItem(BaseModel):
    code: str
    name: str
    secid: str
    last: Optional[float] = None
    change_pct: Optional[float] = None
    avg3m: Optional[float] = None
    avg: Optional[float] = None
    vs_avg_pct: Optional[float] = None
    period_change_pct: Optional[float] = None
    period_high: Optional[float] = None
    period_low: Optional[float] = None
    lot_cost: Optional[float] = None
    bars: Optional[int] = None
    window_start: Optional[str] = None
    window_end: Optional[str] = None


class MainboardPeriodOption(BaseModel):
    value: str
    label: str


class MainboardPoint(BaseModel):
    d: str
    c: float


class MainboardIndexTrend(BaseModel):
    symbol: str
    name: str
    last: Optional[float] = None
    change_pct: Optional[float] = None
    series: List[MainboardPoint] = Field(default_factory=list)


class MainboardPeriodStat(BaseModel):
    value: str
    label: str
    avg: Optional[float] = None
    change_pct: Optional[float] = None
    vs_avg_pct: Optional[float] = None


class MainboardDetailResponse(BaseModel):
    code: str
    name: str
    board: str
    eligible: bool
    block_reason: Optional[str] = None
    period: str
    period_label: str
    last: Optional[float] = None
    change_pct: Optional[float] = None
    price_date: Optional[str] = None
    price_is_stale: bool = False
    lot_cost: Optional[float] = None
    avg: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    vs_avg_pct: Optional[float] = None
    period_change_pct: Optional[float] = None
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    series: List[MainboardPoint] = Field(default_factory=list)
    indexes: List[MainboardIndexTrend] = Field(default_factory=list)
    periods: List[MainboardPeriodStat] = Field(default_factory=list)


class MainboardBlockedItem(BaseModel):
    code: str
    name: str
    reason: str


class MainboardResponse(BaseModel):
    session: str
    ready: bool = False
    period: str = "3m"
    period_label: str = "近3月"
    periods: List[MainboardPeriodOption] = Field(default_factory=list)
    as_of: Optional[datetime] = None
    main_est: int = 0
    cyb: int = 0
    kcb: int = 0
    hs300: int = 0
    eligible: int = 0
    blocked: int = 0
    usable: int = 0
    below: int = 0
    mean_vs: Optional[float] = None
    expensive_lots: int = 0
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    quotes_at: Optional[datetime] = None
    klines_at: Optional[datetime] = None
    items: List[MainboardItem] = Field(default_factory=list)
    blocked_items: List[MainboardBlockedItem] = Field(default_factory=list)
    message: Optional[str] = None


class MainboardRefreshResult(BaseModel):
    ok: bool
    quotes: int = 0
    klines: int = 0
    hs300: int = 0
    message: str


class CountdownIn(BaseModel):
    title: str
    kind: str
    date: Optional[str] = None
    day: Optional[int] = None
    hour: Optional[int] = None
    minute: Optional[int] = None


class CountdownOut(BaseModel):
    id: int
    title: str
    kind: str
    date: Optional[str] = None
    day: Optional[int] = None
    hour: Optional[int] = None
    minute: Optional[int] = None
    builtin: bool = False
    rule_label: str
    next_date: str
    next_ts: int
    status: str
    remaining_seconds: int
    elapsed_days: Optional[int] = None
