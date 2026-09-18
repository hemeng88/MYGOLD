import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

logger = logging.getLogger("mygold.database")


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def _ensure_column(inspector, table: str, column: str, ddl: str) -> None:
    """create_all 只建新表，不会给已存在的表补列，新增字段都要在这里手动 ALTER。

    表名和列名都是代码里写死的常量，不接受外部输入。
    """
    if table not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns(table)}
    if column in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE %s ADD COLUMN %s" % (table, ddl)))


def _migrate_fund_favorites_to_users() -> None:
    """给 fund_favorites 加 user_id。

    加账号之前这张表以 code 为主键，一个基金只能被收藏一次。多账号下必须换成
    代理主键 + (user_id, code) 唯一，而 SQLite 改不了主键，只能整表重建。

    老数据的 user_id 先留空，因为这个函数跑在建初始账号之前、此时可能还没有账号。
    之后由 users.claim_orphan_favorites 认领。重建后再次调用会因为已有 user_id 列而直接跳过。
    """
    inspector = inspect(engine)
    if "fund_favorites" not in inspector.get_table_names():
        return
    old_columns = {col["name"] for col in inspector.get_columns("fund_favorites")}
    if "user_id" in old_columns:
        return

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE fund_favorites RENAME TO fund_favorites_legacy"))
    # 重命名之后 create_all 才会按新模型把 fund_favorites 建出来
    Base.metadata.create_all(bind=engine)

    # 只搬两边都有的列，别假设老表长什么样
    new_columns = {col["name"] for col in inspect(engine).get_columns("fund_favorites")}
    carried = [c for c in ("code", "name", "fund_type", "sort_order", "shares", "cost_price", "added_at") if c in old_columns and c in new_columns]
    columns_sql = ", ".join(carried)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO fund_favorites (user_id, %s) SELECT NULL, %s FROM fund_favorites_legacy"
                % (columns_sql, columns_sql)
            )
        )
        moved = conn.execute(text("SELECT COUNT(*) FROM fund_favorites")).scalar() or 0
        conn.execute(text("DROP TABLE fund_favorites_legacy"))
    logger.info("fund_favorites 已加上 user_id，搬运 %d 条老收藏，等账号建好后认领", moved)


def ensure_schema():
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    # 基金持仓份额和成本价是后加的，老库要补列
    _ensure_column(inspector, "fund_favorites", "shares", "shares FLOAT")
    _ensure_column(inspector, "fund_favorites", "cost_price", "cost_price FLOAT")
    # 报价所属交易日，用来判断净值是否已经把这段涨跌算进去。
    # 老库补出来是 NULL，下一轮报价采集就会填上，在那之前按老逻辑走。
    _ensure_column(inspector, "fund_stock_quotes", "trade_date", "trade_date VARCHAR(10)")
    # 补完列再整表重建，保证老列都能搬过去
    _migrate_fund_favorites_to_users()
    _drop_legacy_rank_holders()


def _drop_legacy_rank_holders() -> None:
    """旧的 fund_rank_holders 已被 fund_theme_holders 取代，直接丢掉。

    那张表是采集结果的缓存，口径换过两次（前十截断、共识度加权），
    现在换成全市场反查，列和含义都不一样了，留着只会占地方。
    """
    inspector = inspect(engine)
    if "fund_rank_holders" not in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE fund_rank_holders"))
    logger.info("已删除旧表 fund_rank_holders，改用全市场反查的 fund_theme_holders")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
