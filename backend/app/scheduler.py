import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .alerts import check_fund_alerts
from .config import settings
from .database import SessionLocal
from .funds.collector import collect_fund_holdings, collect_fund_navs, collect_fund_quotes
from .funds.rankings import collect_rankings
from .market_session import should_poll_quotes
from .notify import notify

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
        check_fund_alerts(db)
    except Exception:
        logger.exception("基金持仓股报价采集失败")
        db.rollback()
        await notify("基金持仓股报价采集失败", level="error")
    finally:
        db.close()


async def job_fund_navs() -> None:
    """开盘前刷一次官方净值。

    16:40 那一轮抓不到当天净值 —— 基金净值要到晚上 20-21 点才公布，
    所以那时拿到的是前一天的。如果只靠它，盘中用的基准就永远差一天。
    早上开盘前再抓一次，此时最新公布的正好是上一交易日，才是当天估值的正确基准。
    """
    db = SessionLocal()
    try:
        result = collect_fund_navs(db)
        logger.info("基金净值（开盘前）：%s", result["message"])
    except Exception:
        logger.exception("开盘前基金净值刷新失败")
        db.rollback()
        await notify("开盘前基金净值刷新失败", level="error")
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
        await notify("基金涨幅榜采集失败", level="error")
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
        await notify("基金持仓采集失败", level="error")
    try:
        navs = collect_fund_navs(db)
        logger.info("基金净值：%s", navs["message"])
    except Exception:
        logger.exception("基金净值采集失败")
        db.rollback()
        await notify("基金净值采集失败", level="error")
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
    # 开盘前把净值基准对齐到上一交易日，见 job_fund_navs 的说明
    scheduler.add_job(
        job_fund_navs,
        "cron",
        day_of_week="mon-fri",
        hour=9,
        minute=10,
        id="fund-navs",
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
