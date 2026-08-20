import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .collectors.service import collect_once
from .config import settings
from .database import SessionLocal

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
    scheduler.start()
    logger.info(
        "调度已启动：每 %ss 采价，每 %ss 同步当日曲线",
        settings.tick_interval_seconds,
        settings.curve_snapshot_interval_seconds,
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
