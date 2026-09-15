from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


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
