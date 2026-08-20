"""归因数据刷新：先补历史日线，再补日历快讯，最后给显著波动日补叙事快讯。"""

import logging
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from ..collectors.flashes import retag_flashes, sync_calendar, sync_narrative_days
from ..collectors.history import sync_history
from ..config import settings
from ..timeutil import now_local
from .attribution import days_needing_narrative

logger = logging.getLogger("mygold.analysis")


async def refresh_attribution_data(
    db: Session,
    window_days: Optional[int] = None,
    with_narrative: bool = True,
) -> dict:
    window = window_days or settings.attribution_window_days
    since = now_local().date() - timedelta(days=window)

    bars_written = await sync_history(db, window)
    # 分类规则可能已经改过，先让存量数据对齐当前规则
    retag_flashes(db)
    calendar_added = await sync_calendar(db, since)
    narrative_added = 0
    if with_narrative:
        days = days_needing_narrative(db, window)
        narrative_added = await sync_narrative_days(db, days)
        logger.info("叙事快讯补齐 %s 条，覆盖 %s 个显著波动日", narrative_added, len(days))

    return {
        "ok": True,
        "bars_written": bars_written,
        "calendar_added": calendar_added,
        "narrative_added": narrative_added,
        "message": "日线 %s 条，日历快讯 %s 条，叙事快讯 %s 条"
        % (bars_written, calendar_added, narrative_added),
    }
