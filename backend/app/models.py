from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class PriceTick(Base):
    __tablename__ = "price_ticks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    source_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    yesterday_price: Mapped[float] = mapped_column(Float, nullable=True)
    change_amt: Mapped[float] = mapped_column(Float, nullable=True)
    change_rate: Mapped[str] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    raw_json: Mapped[str] = mapped_column(Text, nullable=True)


class CurvePoint(Base):
    __tablename__ = "curve_points"
    __table_args__ = (UniqueConstraint("trade_date", "ts", name="uq_curve_date_ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    ts: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)


class DailySummary(Base):
    __tablename__ = "daily_summaries"

    trade_date: Mapped[str] = mapped_column(String(10), primary_key=True)
    open_price: Mapped[float] = mapped_column(Float, nullable=True)
    high_price: Mapped[float] = mapped_column(Float, nullable=True)
    low_price: Mapped[float] = mapped_column(Float, nullable=True)
    close_price: Mapped[float] = mapped_column(Float, nullable=True)
    prev_close: Mapped[float] = mapped_column(Float, nullable=True)
    change_amt: Mapped[float] = mapped_column(Float, nullable=True)
    change_rate: Mapped[float] = mapped_column(Float, nullable=True)
    point_count: Mapped[int] = mapped_column(Integer, default=0)
    first_ts: Mapped[int] = mapped_column(Integer, nullable=True)
    last_ts: Mapped[int] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class MarketEvent(Base):
    __tablename__ = "market_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    start_price: Mapped[float] = mapped_column(Float, nullable=False)
    end_price: Mapped[float] = mapped_column(Float, nullable=False)
    change_amt: Mapped[float] = mapped_column(Float, nullable=False)
    change_rate: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_rate: Mapped[float] = mapped_column(Float, nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    ts: Mapped[int] = mapped_column(Integer, nullable=True)
    headline: Mapped[str] = mapped_column(String(300), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=True)
    url: Mapped[str] = mapped_column(String(500), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    tags: Mapped[str] = mapped_column(String(200), nullable=True)


class DailyBar(Base):
    """代理标的的历史日线，用来做长周期归因（当前用沪金连续 AU0）。"""

    __tablename__ = "daily_bars"
    __table_args__ = (UniqueConstraint("symbol", "trade_date", name="uq_bar_symbol_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    open_price: Mapped[float] = mapped_column(Float, nullable=True)
    high_price: Mapped[float] = mapped_column(Float, nullable=True)
    low_price: Mapped[float] = mapped_column(Float, nullable=True)
    close_price: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class NewsFlash(Base):
    """带标签的财经快讯归档，只保留能对上事件类型的条目。"""

    __tablename__ = "news_flashes"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_flash_source_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    # 归属交易日：18:00 之后的快讯计入下一个交易日
    session_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    tags: Mapped[str] = mapped_column(String(200), nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    url: Mapped[str] = mapped_column(String(500), nullable=True)


class StockQuote(Base):
    """A 股自选池最新报价，和积存金报价表分开。"""

    __tablename__ = "stock_quotes"

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    prev_close: Mapped[float] = mapped_column(Float, nullable=True)
    open_price: Mapped[float] = mapped_column(Float, nullable=True)
    high_price: Mapped[float] = mapped_column(Float, nullable=True)
    low_price: Mapped[float] = mapped_column(Float, nullable=True)
    volume: Mapped[float] = mapped_column(Float, nullable=True)
    amount: Mapped[float] = mapped_column(Float, nullable=True)
    change_amt: Mapped[float] = mapped_column(Float, nullable=True)
    change_rate: Mapped[float] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class StockBar(Base):
    """A 股日线，用来算均线和 ATR。"""

    __tablename__ = "stock_bars"
    __table_args__ = (UniqueConstraint("code", "trade_date", name="uq_stock_bar_code_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    open_price: Mapped[float] = mapped_column(Float, nullable=True)
    high_price: Mapped[float] = mapped_column(Float, nullable=True)
    low_price: Mapped[float] = mapped_column(Float, nullable=True)
    close_price: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class StockNews(Base):
    """观察池相关公告和资讯，只用来给倾向，不当预测准星。"""

    __tablename__ = "stock_news"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_stock_news_source_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(80), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(400), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    tags: Mapped[str] = mapped_column(String(80), nullable=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    collected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class GoldLot(Base):
    __tablename__ = "gold_lots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    grams: Mapped[float] = mapped_column(Float, nullable=False)
    buy_price: Mapped[float] = mapped_column(Float, nullable=False)
    bought_at: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    note: Mapped[str] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FundFavorite(Base):
    """收藏的基金，单用户，代码就是主键。

    shares / cost_price 是手动填的持仓，用来把估算涨跌换算成具体的盈亏金额。
    留空表示只看不持有。
    """

    __tablename__ = "fund_favorites"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    fund_type: Mapped[str] = mapped_column(String(32), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 持有份额
    shares: Mapped[float] = mapped_column(Float, nullable=True)
    # 每份成本价（元）
    cost_price: Mapped[float] = mapped_column(Float, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FundHolding(Base):
    """基金公示的股票持仓，季报级别，只在换季或手动刷新时更新。"""

    __tablename__ = "fund_holdings"
    __table_args__ = (UniqueConstraint("fund_code", "secid", name="uq_fund_holding_fund_secid"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_code: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    # 东方财富 secid，形如 1.600519 / 0.000568 / 116.00700，直接能拿去查行情
    secid: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    stock_code: Mapped[str] = mapped_column(String(16), nullable=False)
    stock_name: Mapped[str] = mapped_column(String(48), nullable=True)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    # 占基金净值比例，百分数，例如 17.28
    weight_pct: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=True)
    report_date: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FundStockQuote(Base):
    """基金持仓股的最新报价，按 secid 存，和 A 股观察池那张表互不干扰。"""

    __tablename__ = "fund_stock_quotes"

    secid: Mapped[str] = mapped_column(String(24), primary_key=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(48), nullable=True)
    market: Mapped[str] = mapped_column(String(8), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=True)
    prev_close: Mapped[float] = mapped_column(Float, nullable=True)
    # 涨跌幅，百分数，例如 -0.89
    change_pct: Mapped[float] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FundNav(Base):
    """基金官方净值，只留最新一条，用来把估算涨跌换算成估算净值。"""

    __tablename__ = "fund_navs"

    code: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=True)
    nav: Mapped[float] = mapped_column(Float, nullable=True)
    acc_nav: Mapped[float] = mapped_column(Float, nullable=True)
    nav_date: Mapped[str] = mapped_column(String(10), nullable=True)
    # 官方公布的上一个净值日涨跌幅，百分数
    nav_chg_pct: Mapped[float] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FundRankEntry(Base):
    """公募基金涨幅榜，按周期存前若干名。定时任务刷，页面只读库。"""

    __tablename__ = "fund_rank_entries"
    __table_args__ = (UniqueConstraint("period", "code", name="uq_fund_rank_period_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 周期键，对应 sources.RANK_PERIODS，例如 jnzf / 3yzf
    period: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(12), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # 该周期涨幅，百分数
    return_pct: Mapped[float] = mapped_column(Float, nullable=False)
    nav: Mapped[float] = mapped_column(Float, nullable=True)
    nav_date: Mapped[str] = mapped_column(String(10), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class FundRankStock(Base):
    """把榜单基金的重仓股汇总起来，用来看这个周期领涨的是哪个方向。"""

    __tablename__ = "fund_rank_stocks"
    __table_args__ = (UniqueConstraint("period", "stock_code", name="uq_fund_rank_stock"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    stock_code: Mapped[str] = mapped_column(String(16), nullable=False)
    stock_name: Mapped[str] = mapped_column(String(48), nullable=True)
    secid: Mapped[str] = mapped_column(String(24), nullable=True)
    # 出现在榜单里几只基金的重仓中
    fund_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 这些基金给它的权重之和，百分数
    weight_sum: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
