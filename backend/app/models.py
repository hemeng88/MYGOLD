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


class FundRankHolder(Base):
    """在榜单基金里，谁的仓位最集中在这个周期的主线上。

    和 FundRankStock 是同一次采集的两个产物：那张表按股票聚合，这张表按基金聚合。
    采集时逐只基金的持仓只存在内存里，所以名次必须在那时算完落库，页面只读。
    """

    __tablename__ = "fund_rank_holders"
    __table_args__ = (UniqueConstraint("period", "fund_code", name="uq_fund_rank_holder"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    period: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    fund_code: Mapped[str] = mapped_column(String(12), nullable=False)
    fund_name: Mapped[str] = mapped_column(String(64), nullable=True)
    # 主线得分 = Σ(持仓权重 × 该股共识度)，共识度 = 多少只榜单基金重仓它 / 榜单总数。
    # 不用「前 N 大重仓股集合」那种口径：集合放大后会覆盖几乎所有持仓，榜会退化成
    # 「谁满仓程度最高」。加权方式让全榜数据都参与，又不需要人为截断。
    theme_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    # 得分占自身披露仓位的比例，衡量这个组合有多随大流
    consensus_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    # 持仓里和别的榜单基金抱团的只数 / 公示持仓总只数
    shared_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    holding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 该基金公示持仓的总权重，用来看这个集中度占它披露仓位的多少
    disclosed_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    # 持仓完全相同的同门份额（A/C 类），逗号分隔。合并进这一行，免得挤占名次
    alt_codes: Mapped[str] = mapped_column(String(120), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
