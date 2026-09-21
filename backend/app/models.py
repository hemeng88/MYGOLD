from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint
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


class User(Base):
    """登录账号。密码只存 PBKDF2 加盐哈希，格式见 users.py。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_login_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class FundAlertState(Base):
    """记录每只基金最近一次成功提醒的日内估算涨跌，作为下一次提醒的基准。"""

    __tablename__ = "fund_alert_states"
    __table_args__ = (UniqueConstraint("user_id", "fund_code", name="uq_fund_alert_state"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    fund_code: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    trade_date: Mapped[str] = mapped_column(String(10), nullable=False)
    last_estimate_pct: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

class FundThemeHolder(Base):
    """全市场反查：谁把最多净值压在这个周期的主线代表股上。

    比较范围是全市场，不再局限于涨幅榜里的基金 —— 之前用「因为押中主线而上榜」的
    基金去衡量谁押中主线，是循环论证。主线仍由涨幅榜识别，候选基金来自
    RPT_MAIN_ORGHOLDDETAIL 的股票反查。

    theme_pct 直接是「占该基金净值比例」之和，是个能验算、能横向比的百分数。
    """

    __tablename__ = "fund_theme_holders"
    __table_args__ = (UniqueConstraint("period", "fund_code", name="uq_fund_theme_holder"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    fund_code: Mapped[str] = mapped_column(String(12), nullable=False)
    fund_name: Mapped[str] = mapped_column(String(80), nullable=True)
    fund_type: Mapped[str] = mapped_column(String(32), nullable=True)
    # 该基金净值里有多少比例压在这条主线的代表股上，百分数
    theme_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    # 命中了几只代表股 / 这条主线一共几只代表股
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    theme_stock_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 命中股票被多少只榜单基金重仓的累计数，看押的是不是最抱团的那几只
    consensus_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 同门份额（A/C 类），按去掉尾部份额字母的名字归并
    alt_codes: Mapped[str] = mapped_column(String(120), nullable=True)
    report_date: Mapped[str] = mapped_column(String(10), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
