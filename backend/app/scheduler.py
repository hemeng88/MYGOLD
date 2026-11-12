import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .analysis.portfolio_summary import format_close_report, portfolio_summary
from .config import settings
from .database import SessionLocal
from .funds.collector import collect_fund_holdings, collect_fund_navs, collect_fund_quotes
from .funds.rankings import collect_rankings
from .funds.sources import fetch_market_trade_date
from .gold import fetch_gold_quote
from .market_session import should_poll_quotes
from .notify import notify
from .stocks.collector import collect_quotes as collect_mainboard_quotes
from .stocks.collector import collect_universe as collect_mainboard_universe
from .stocks.collector import has_usable_rows
from .timeutil import trade_date_today
from .users import get_user

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


async def job_portfolio_close_report() -> None:
    """交易日 16:10 刷新数据库全部实际持仓，给指定账号发一次整体收盘播报。"""
    today = trade_date_today()
    try:
        market_trade_date = fetch_market_trade_date(max_age_seconds=0)
    except Exception:
        logger.exception("收盘播报无法确认交易日")
        return
    if market_trade_date != today:
        logger.info("收盘播报跳过：%s 不是 A 股交易日（最近交易日 %s）", today, market_trade_date)
        return

    db = SessionLocal()
    try:
        username = (settings.openclaw_report_username or settings.bootstrap_username).strip()
        user = get_user(db, username)
        if user is None:
            logger.error("收盘播报跳过：数据库里没有账号 %s", username)
            return

        # 盘中轮询 15:10 已停。16:10 再拉一次，既拿 A 股收盘价，也拿港股收盘价；
        # 采集范围来自所有账号数据库收藏，随后 summary 只读取指定账号。
        try:
            result = collect_fund_quotes(db)
            logger.info("收盘播报前刷新持仓报价：%s", result["message"])
        except Exception:
            logger.exception("收盘播报前刷新持仓报价失败，使用库里最后一份报价")
            db.rollback()

        summary = portfolio_summary(db, user.id, trade_date=market_trade_date)
        if not summary["position_count"]:
            logger.info("收盘播报跳过：账号 %s 没有填写持仓", username)
            return

        gold_price = None
        try:
            gold_price = (await fetch_gold_quote()).price
        except Exception:
            # 金价失败不能吃掉整份持仓播报；正文会明确显示「获取失败」。
            logger.exception("收盘播报实时金价获取失败")

        body = format_close_report(summary, gold_price, market_trade_date)
        sent = await notify("每日持仓收盘播报", body=body)
        if sent:
            logger.info("已发送 %s 的每日持仓收盘播报（%d 只）", username, summary["position_count"])
        else:
            logger.error("%s 的每日持仓收盘播报未发送成功", username)
    except Exception:
        logger.exception("每日持仓收盘播报生成失败")
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
        job_portfolio_close_report,
        "cron",
        day_of_week="mon-fri",
        hour=settings.portfolio_report_hour,
        minute=settings.portfolio_report_minute,
        id="portfolio-close-report",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info(
        "调度已启动：A股盘中每 %ss 刷持仓股和主板现价，%02d:%02d 推送持仓收盘播报，16:40 对季报持仓，16:50 重算主板均价，21:30 拉涨幅榜",
        settings.fund_quote_interval_seconds,
        settings.portfolio_report_hour,
        settings.portfolio_report_minute,
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
