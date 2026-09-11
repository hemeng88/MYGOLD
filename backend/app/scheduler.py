import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .analysis.refresh import refresh_attribution_data
from .collectors.service import collect_once
from .config import settings
from .database import SessionLocal
from .funds.collector import collect_fund_holdings, collect_fund_navs, collect_fund_quotes
from .stocks.collector import collect_bars, collect_quotes
from .stocks.news import collect_news
from .stocks.universe import should_poll_quotes

logger = logging.getLogger("mygold.scheduler")
scheduler = AsyncIOScheduler(timezone=settings.timezone)


async def _run_collect(include_chart: bool) -> None:
    db = SessionLocal()
    try:
        result = await collect_once(db, include_chart=include_chart)
        logger.info("%s upserted=%s", result.message, result.curve_points_upserted)
    except Exception:
        logger.exception("定时采集失败")
        db.rollback()
    finally:
        db.close()


async def job_tick() -> None:
    await _run_collect(include_chart=False)


async def job_curve() -> None:
    await _run_collect(include_chart=True)


async def job_attribution() -> None:
    db = SessionLocal()
    try:
        result = await refresh_attribution_data(db)
        logger.info("归因数据刷新：%s", result["message"])
    except Exception:
        logger.exception("归因数据刷新失败")
        db.rollback()
    finally:
        db.close()
    await job_stock_bars()


async def job_stock_quotes() -> None:
    if not should_poll_quotes():
        return
    db = SessionLocal()
    try:
        result = collect_quotes(db)
        logger.info("A股报价：%s", result["message"])
    except Exception:
        logger.exception("A股报价采集失败")
        db.rollback()
    finally:
        db.close()


async def job_stock_news() -> None:
    db = SessionLocal()
    try:
        result = await collect_news(db)
        logger.info("股票资讯：%s", result["message"])
    except Exception:
        logger.exception("股票资讯采集失败")
        db.rollback()
    finally:
        db.close()


async def job_stock_bars() -> None:
    db = SessionLocal()
    try:
        result = await collect_bars(db)
        logger.info("A股日线：%s", result["message"])
    except Exception:
        logger.exception("A股日线采集失败")
        db.rollback()
    finally:
        db.close()


async def job_fund_quotes() -> None:
    """开盘时段刷收藏基金的持仓股报价，估值就是拿这个算的。"""
    if not should_poll_quotes():
        return
    db = SessionLocal()
    try:
        result = collect_fund_quotes(db)
        logger.info("基金持仓股报价：%s", result["message"])
    except Exception:
        logger.exception("基金持仓股报价采集失败")
        db.rollback()
    finally:
        db.close()


async def job_fund_holdings() -> None:
    """季报持仓一个季度才换一次，每天收盘后对一遍就够，顺手更新官方净值。"""
    db = SessionLocal()
    try:
        holdings = collect_fund_holdings(db)
        logger.info("基金持仓：%s", holdings["message"])
    except Exception:
        logger.exception("基金持仓采集失败")
        db.rollback()
    try:
        navs = collect_fund_navs(db)
        logger.info("基金净值：%s", navs["message"])
    except Exception:
        logger.exception("基金净值采集失败")
        db.rollback()
    finally:
        db.close()


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(
        job_tick,
        "interval",
        seconds=settings.tick_interval_seconds,
        id="tick",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        job_curve,
        "interval",
        seconds=settings.curve_snapshot_interval_seconds,
        id="curve",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # 收盘前再固化一次当日曲线，避免跨日后第三方接口只剩新一天数据
    scheduler.add_job(
        job_curve,
        "cron",
        hour=23,
        minute=55,
        id="finalize-curve",
        replace_existing=True,
        max_instances=1,
    )
    # 收盘后更新一次归因数据：日线出完、当天快讯也齐了
    scheduler.add_job(
        job_attribution,
        "cron",
        hour=16,
        minute=20,
        id="attribution",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        job_stock_quotes,
        "interval",
        seconds=settings.stock_quote_interval_seconds,
        id="stock-quotes",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        job_stock_news,
        "interval",
        seconds=settings.stock_news_interval_seconds,
        id="stock-news",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        job_fund_quotes,
        "interval",
        seconds=settings.fund_quote_interval_seconds,
        id="fund-quotes",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # 收盘后再对一次季报持仓，换季那几天才会真的有变化
    scheduler.add_job(
        job_fund_holdings,
        "cron",
        hour=16,
        minute=40,
        id="fund-holdings",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "调度已启动：每 %ss 采价，每 %ss 同步当日曲线，A股开盘每 %ss 刷报价，资讯每 %ss，基金持仓股每 %ss",
        settings.tick_interval_seconds,
        settings.curve_snapshot_interval_seconds,
        settings.stock_quote_interval_seconds,
        settings.stock_news_interval_seconds,
        settings.fund_quote_interval_seconds,
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
