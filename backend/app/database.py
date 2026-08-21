from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def ensure_schema():
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    if "market_events" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("market_events")}
    if "tags" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE market_events ADD COLUMN tags VARCHAR(200) DEFAULT ''"))


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
