from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


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


def ensure_schema():
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    _ensure_column(inspector, "market_events", "tags", "tags VARCHAR(200) DEFAULT ''")
    # 基金持仓份额和成本价是后加的，老库要补列
    _ensure_column(inspector, "fund_favorites", "shares", "shares FLOAT")
    _ensure_column(inspector, "fund_favorites", "cost_price", "cost_price FLOAT")


def backfill_event_tags():
    from sqlalchemy import select

    from .collectors.news import classify_tags
    from .models import MarketEvent

    db = SessionLocal()
    try:
        rows = db.scalars(select(MarketEvent)).all()
        changed = False
        for row in rows:
            if row.tags:
                continue
            row.tags = ",".join(classify_tags("%s %s" % (row.headline, row.summary or "")))
            changed = True
        if changed:
            db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
