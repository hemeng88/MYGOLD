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


class FundRankHolderItem(BaseModel):
    rank: int
    code: str
    name: Optional[str] = None
    fund_type: Optional[str] = None
    # 该基金净值里有多少比例压在这条主线的代表股上，百分数
    theme_pct: float
    hit_count: int
    theme_stock_count: int
    # 命中股票被多少只榜单基金重仓的累计数
    consensus_hits: int
    # 同门份额（A/C 类），已合并到本行
    alt_codes: List[str] = Field(default_factory=list)
    # 按该基金披露重仓股当前涨跌推算的日内涨幅（较昨收）
    estimate_pct: Optional[float] = None


class FundRankResponse(BaseModel):
    period: str
    period_label: Optional[str] = None
    periods: List[FundRankPeriod] = Field(default_factory=list)
    as_of: Optional[datetime] = None
    funds: List[FundRankFund] = Field(default_factory=list)
    hot_stocks: List[FundRankStockItem] = Field(default_factory=list)
    # 该周期实际采集了多少只基金（展示的 funds 可能只是前几名）
    board_size: int = 0
    # 被两只以上榜单基金共同重仓的股票数，说明这条主线有多集中
    theme_stock_count: int = 0
    # 这条主线用了几只代表股去做全市场反查
    theme_stock_n: int = 0
    # 反查用的报告期
    holder_report_date: Optional[str] = None
    top_holders: List[FundRankHolderItem] = Field(default_factory=list)
    message: Optional[str] = None


class FundRankRefreshResult(BaseModel):
    ok: bool
    periods: int = 0
    funds: int = 0
    message: str


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    token: str
    username: str


class MeOut(BaseModel):
    username: str


class ExposureFundItem(BaseModel):
    """某只股票的持仓金额来自哪只基金。"""

    code: str
    name: Optional[str] = None
    # 该股占这只基金净值的比例，百分数
    weight_pct: float
    value: float


class ExposureItem(BaseModel):
    code: str
    name: Optional[str] = None
    market: Optional[str] = None
    # 穿透后你在这只股票上对应多少钱
    value: float
    # 占你全部基金市值的比例
    pct_of_total: Optional[float] = None
    change_pct: Optional[float] = None
    # 今天这只股票给你带来的盈亏金额
    today_pnl: Optional[float] = None
    fund_count: int = 0
    funds: List[ExposureFundItem] = Field(default_factory=list)


class ExposureResponse(BaseModel):
    session: str
    as_of: Optional[datetime] = None
    fund_count: int = 0
    total_value: Optional[float] = None
    # 能穿透到个股的金额，和总市值的差额是未公示仓位加债券现金
    disclosed_value: Optional[float] = None
    coverage_pct: Optional[float] = None
    today_pnl: Optional[float] = None
    # 所有基金的最新净值都已结算上一个交易日，今日盈亏要等开盘
    settled: bool = False
    stock_count: int = 0
    items: List[ExposureItem] = Field(default_factory=list)
    ready: bool = False
    message: Optional[str] = None
