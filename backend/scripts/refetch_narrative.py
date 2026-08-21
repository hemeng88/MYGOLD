"""分类规则放宽后重抓叙事快讯。

当初标不上标签的条目直接被丢了，没有进库，retag_flashes 救不回来，
只能按交易日重新翻一遍窗口。已入库的条目按 external_id 去重，重复跑是安全的。

用法：python backend/scripts/refetch_narrative.py [窗口天数]
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analysis.attribution import days_needing_narrative
from app.collectors.flashes import sync_narrative_days
from app.database import SessionLocal


async def main() -> None:
    window = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    db = SessionLocal()
    days = days_needing_narrative(db, window)
    print("覆盖 %d 个交易日：%s ~ %s" % (len(days), days[0], days[-1]))
    added = await sync_narrative_days(db, days, force=True)
    print("新增 %d 条" % added)
    db.close()


if __name__ == "__main__":
    asyncio.run(main())
