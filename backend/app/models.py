from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class FundFavorite(Base):
    """某个账号收藏的基金。这是唯一按账号隔离的表。

    shares / cost_price 是手动填的持仓，用来把估算涨跌换算成具体的盈亏金额。
    留空表示只看不持有。

    user_id 可空只是为了兼容加账号之前的老数据：那些行迁移后先挂空，
    等系统里只有一个账号时由 users.claim_orphan_favorites 认领过去。
    """

    __tablename__ = "fund_favorites"
    __table_args__ = (UniqueConstraint("user_id", "code", name="uq_fund_favorite_user_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    fund_type: Mapped[str] = mapped_column(String(32), nullable=True)
    # 收藏类型：fund 为基金，stock 为单只股票。共用收藏/持仓表，便于前端统一展示。
    asset_type: Mapped[str] = mapped_column(String(12), nullable=False, default="fund")
    # 股票收藏直接绑定行情接口使用的 secid；基金收藏为空。
    secid: Mapped[str] = mapped_column(String(24), nullable=True)
    market: Mapped[str] = mapped_column(String(8), nullable=True)
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
    # change_pct 属于哪个交易日（A 股日历，形如 2026-09-18）。
    # collected_at 不能代替它：收盘后、周末、节假日照样能采到数据，
    # 拿到的却还是上一场的涨跌幅。净值日一旦推到同一天，估算就会把这段行情算两遍。
    trade_date: Mapped[str] = mapped_column(String(10), nullable=True)
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


class User(Base):
    """登录账号。密码只存 PBKDF2 加盐哈希，格式见 users.py。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_login_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class MainboardMeta(Base):
    """沪深主板规模和沪深300样本的刷新状态，只留一行。"""

    __tablename__ = "mainboard_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hs_a: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sh_a: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sz_a: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cyb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kcb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    main_est: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hs300_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligible_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    usable_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quotes_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    klines_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    message: Mapped[str] = mapped_column(String(240), nullable=True)


class MainboardStock(Base):
    """沪深300成分的主板可买样本，以及买不了的拦截名单。"""

    __tablename__ = "mainboard_stocks"

    secid: Mapped[str] = mapped_column(String(24), primary_key=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(48), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    board: Mapped[str] = mapped_column(String(16), nullable=False)
    eligible: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    block_reason: Mapped[str] = mapped_column(String(16), nullable=True)
    last: Mapped[float] = mapped_column(Float, nullable=True)
    change_pct: Mapped[float] = mapped_column(Float, nullable=True)
    avg3m: Mapped[float] = mapped_column(Float, nullable=True)
    vs_avg_pct: Mapped[float] = mapped_column(Float, nullable=True)
    bars: Mapped[int] = mapped_column(Integer, nullable=True)
    window_start: Mapped[str] = mapped_column(String(10), nullable=True)
    window_end: Mapped[str] = mapped_column(String(10), nullable=True)
    lot_cost: Mapped[float] = mapped_column(Float, nullable=True)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=True)
    quote_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    kline_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    # 近一年前复权收盘 [[日期, 收盘], ...]，详情走势和各周期均价都从这里算
    closes_json: Mapped[str] = mapped_column(Text, nullable=True)
    # {周期: {avg, high, low, first, bars, start, end}}
    periods_json: Mapped[str] = mapped_column(Text, nullable=True)


class DeepSeekAccountConfig(Base):
    __tablename__ = "deepseek_account_configs"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    revision: Mapped[str] = mapped_column(String(36), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False, default="deepseek")
    base_url: Mapped[str] = mapped_column(String(512), nullable=False, default="https://api.deepseek.com")
    json_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="json_object")
    token_field: Mapped[str] = mapped_column(String(32), nullable=False, default="max_tokens")


class StockAIProfile(Base):
    __tablename__ = "stock_ai_profiles"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    json_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    token_field: Mapped[str] = mapped_column(String(32), nullable=False)
    revision: Mapped[str] = mapped_column(String(36), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class StockResearchPreference(Base):
    __tablename__ = "stock_research_preferences"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    boards_json: Mapped[str] = mapped_column(Text, nullable=False)
    price_min: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    price_max: Mapped[float] = mapped_column(Float().evaluates_none(), nullable=True, default=50)


class StockHistorySnapshot(Base):
    __tablename__ = "stock_history_snapshots"
    __table_args__ = (UniqueConstraint("symbol", "as_of", name="uq_stock_history_snapshot"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), nullable=False)
    as_of: Mapped[str] = mapped_column(String(10), nullable=False)
    bars_json: Mapped[str] = mapped_column(Text, nullable=False)


class StockRuleEvaluation(Base):
    __tablename__ = "stock_rule_evaluations"
    scope: Mapped[str] = mapped_column(String(128), primary_key=True)
    as_of: Mapped[str] = mapped_column(String(10), nullable=False)
    report_json: Mapped[str] = mapped_column(Text, nullable=False)


class StockMarketArchive(Base):
    __tablename__ = "stock_market_archives"
    trade_date: Mapped[str] = mapped_column(String(10), primary_key=True)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)


class StrategyObservation(Base):
    """保存首次出现的策略候选；后续用完整日线做前向事件跟踪，不是真实委托。"""

    __tablename__ = "strategy_observations"
    __table_args__ = (UniqueConstraint("version", "signal_date", "code", "strategy", name="uq_strategy_observation"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    signal_date: Mapped[str] = mapped_column(String(10), nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    strategy: Mapped[str] = mapped_column(String(16), nullable=False)
    reference_price: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    entry_date: Mapped[str] = mapped_column(String(10), nullable=True)
    exit_date: Mapped[str] = mapped_column(String(10), nullable=True)
    net_pct: Mapped[float] = mapped_column(Float, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class StockCloseWatchlist(Base):
    """按板块范围保存最近一份成功生成的收盘观察池，不包含用户或AI密钥。"""

    __tablename__ = "stock_close_watchlists"
    scope: Mapped[str] = mapped_column(String(128), primary_key=True)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)


class StockCloseArchive(Base):
    """每日收盘候选原始快照；与最新观察池分开，供后续判断使用。"""

    __tablename__ = "stock_close_archives"
    __table_args__ = (UniqueConstraint("scope", "trade_date", name="uq_stock_close_archive"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(128), nullable=False)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)


class StockSimAccount(Base):
    __tablename__ = "stock_sim_accounts"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False)
    cash_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    peak_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    running: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    enabled_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    entry_day: Mapped[str] = mapped_column(String(10), nullable=True)
    message: Mapped[str] = mapped_column(String(240), nullable=True)


class StockSimPosition(Base):
    __tablename__ = "stock_sim_positions"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mark_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    marked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    exit_reason: Mapped[str] = mapped_column(String(40), nullable=True)
    last_fill_quote_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class StockSimTrade(Base):
    __tablename__ = "stock_sim_trades"
    __table_args__ = (UniqueConstraint("user_id", "symbol", "side", "quoted_at", name="uq_stock_sim_fill"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    fees_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    realized_cents: Mapped[int] = mapped_column(BigInteger, nullable=True)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    signal_day: Mapped[str] = mapped_column(String(10), nullable=True)
    filled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    quoted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class StockSimEquity(Base):
    __tablename__ = "stock_sim_equity"
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_day: Mapped[str] = mapped_column(String(10), primary_key=True)
    equity_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cash_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_benchmark: Mapped[float] = mapped_column(Float, nullable=True)
    benchmark: Mapped[float] = mapped_column(Float, nullable=True)
    stale_positions: Mapped[int] = mapped_column(Integer, nullable=False)
    final_mark: Mapped[bool] = mapped_column(nullable=False, default=False)
    marked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class StockAIReview(Base):
    """保存某个账号一次成功的手动点评及模型实际收到的公开数据。"""

    __tablename__ = "stock_ai_reviews"
    review_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_scope: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    scan_scope: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[str] = mapped_column(String(12), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_at: Mapped[str] = mapped_column(String(32), nullable=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    candidates_json: Mapped[str] = mapped_column(Text, nullable=False)
    input_json: Mapped[str] = mapped_column(Text, nullable=False)
    report_json: Mapped[str] = mapped_column(Text, nullable=False)


class StockAIReviewLatest(Base):
    """每条配置在某个行情范围内对每只股票最新的已归档点评。"""
    __tablename__ = "stock_ai_review_latest"
    account_scope: Mapped[str] = mapped_column(String(80), primary_key=True)
    scan_scope: Mapped[str] = mapped_column(String(128), primary_key=True)
    mode: Mapped[str] = mapped_column(String(12), primary_key=True)
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    review_id: Mapped[str] = mapped_column(String(64), nullable=False)


class CountdownItem(Base):
    """账号私有的倒计时。单次日期或每月循环，可选到分钟。"""

    __tablename__ = "countdown_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(40), nullable=False)
    # once 单次，monthly 每月
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    # once 用，YYYY-MM-DD
    date: Mapped[str] = mapped_column(String(10), nullable=True)
    # monthly 用，1-31
    day: Mapped[int] = mapped_column(Integer, nullable=True)
    hour: Mapped[int] = mapped_column(Integer, nullable=True)
    minute: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
