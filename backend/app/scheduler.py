import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import settings
from .database import SessionLocal
from .funds.collector import collect_fund_holdings, collect_fund_navs, collect_fund_quotes
from .market_session import should_poll_quotes
from .stocks.collector import collect_quotes as collect_mainboard_quotes
from .stocks.collector import collect_universe as collect_mainboard_universe
from .stocks.collector import has_usable_rows
from .stocks.signals import queue_close_archives, queue_scans
from .stocks.simulator import run_cycle as run_stock_simulator

logger = logging.getLogger("mygold.scheduler")
scheduler = AsyncIOScheduler(timezone=settings.timezone)


async def job_stock_close_archive() -> None:
    try:
        logger.info("收盘候选自动归档：已安排 %d 个板块范围", queue_close_archives())
    except Exception:
        logger.exception("收盘候选自动归档安排失败")


def job_stock_simulator() -> None:
    try:
        run_stock_simulator()
    except Exception:
        logger.exception("模拟盘行情检查失败")


async def job_stock_scan() -> None:
    try:
        queue_scans()
    except Exception:
        logger.exception("后台股票扫描安排失败")


async def job_stock_history_bootstrap() -> None:
    try:
        queue_scans(bootstrap=True)
    except Exception:
        logger.exception("股票历史初始化安排失败")


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
    finally:
        db.close()


async def job_mainboard_quotes() -> None:
    """开盘时段刷沪深300主板样本现价，各周期均价偏离在列表接口里按现价现算。"""
    if not should_poll_quotes():
        return
    db = SessionLocal()
    try:
        if not has_usable_rows(db):
            return
        result = collect_mainboard_quotes(db)
        logger.info("主板样本现价：%s", result["message"])
    except Exception:
        logger.exception("主板样本现价采集失败")
        db.rollback()
    finally:
        db.close()


async def job_mainboard_klines() -> None:
    """收盘后重拉近一年日线。名单和各周期均价一天变一次。"""
    db = SessionLocal()
    try:
        result = collect_mainboard_universe(db)
        logger.info("主板样本日线：%s", result["message"])
        collect_mainboard_quotes(db)
    except Exception:
        logger.exception("主板样本日线采集失败")
        db.rollback()
    finally:
        db.close()


async def job_mainboard_bootstrap() -> None:
    """库里还没有样本（或老库只有三月均价）时启动补一刀，免得页面一直空着。"""
    db = SessionLocal()
    try:
        if has_usable_rows(db):
            return
        result = collect_mainboard_universe(db)
        logger.info("主板样本启动补齐：%s", result["message"])
        collect_mainboard_quotes(db)
    except Exception:
        logger.exception("主板样本启动补齐失败")
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
    scheduler.add_job(
        job_mainboard_quotes,
        "interval",
        seconds=settings.fund_quote_interval_seconds,
        id="mainboard-quotes",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        job_mainboard_klines,
        "cron",
        hour=16,
        minute=50,
        id="mainboard-klines",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        job_mainboard_bootstrap,
        "date",
        id="mainboard-bootstrap",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        job_stock_close_archive,
        "cron",
        day_of_week="mon-fri",
        hour="16,17",
        minute=0,
        id="stock-close-archive",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(job_stock_scan, "interval", seconds=120, id="stock-scan",
                      replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(job_stock_history_bootstrap, "date", id="stock-history-bootstrap",
                      replace_existing=True, max_instances=1)
    scheduler.add_job(job_stock_simulator, "interval", seconds=60, id="stock-simulator",
                      replace_existing=True, max_instances=1, coalesce=True)
    scheduler.start()
    logger.info(
        "调度已启动：A股盘中每 %ss 刷持仓股和主板现价，16:40 对季报持仓，16:50 重算主板均价",
        settings.fund_quote_interval_seconds,
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
