import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import settings
from .database import SessionLocal
from .funds.collector import collect_fund_holdings, collect_fund_navs, collect_fund_quotes
from .funds.rankings import collect_rankings
from .market_session import should_poll_quotes

logger = logging.getLogger("mygold.scheduler")
scheduler = AsyncIOScheduler(timezone=settings.timezone)


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


async def job_fund_rankings() -> None:
    """涨幅榜基于 T-1 净值，一天变一次，收盘后跑一遍就够。"""
    db = SessionLocal()
    try:
        result = collect_rankings(db)
        logger.info("基金涨幅榜：%s", result["message"])
    except Exception:
        logger.exception("基金涨幅榜采集失败")
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
    # 榜单要等当日净值出齐，放晚一点
    scheduler.add_job(
        job_fund_rankings,
        "cron",
        hour=21,
        minute=30,
        id="fund-rankings",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "调度已启动：A股盘中每 %ss 刷持仓股报价，16:40 对季报持仓，21:30 拉涨幅榜",
        settings.fund_quote_interval_seconds,
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
