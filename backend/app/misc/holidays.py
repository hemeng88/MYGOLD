"""内地法定节假日：国务院办公厅每年通知里的放假调休区间。

只收录放假日，不含「周末调班上班」那天。区间内都算这次假期，
过了最后一天才翻到下一轮。日期以国办发明电为准，不自己推农历。

表只覆盖已经发通知的年份。下一年通知出来后再补，缺年份时列表里不出现这条。
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Tuple

# (名称, 放假第一天, 放假最后一天)
Holiday = Tuple[str, date, date]

HOLIDAYS: Tuple[Holiday, ...] = (
    # 国办发明电〔2025〕7号
    ("元旦", date(2026, 1, 1), date(2026, 1, 3)),
    ("春节", date(2026, 2, 15), date(2026, 2, 23)),
    ("清明节", date(2026, 4, 4), date(2026, 4, 6)),
    ("劳动节", date(2026, 5, 1), date(2026, 5, 5)),
    ("端午节", date(2026, 6, 19), date(2026, 6, 21)),
    ("中秋节", date(2026, 9, 25), date(2026, 9, 27)),
    ("国庆节", date(2026, 10, 1), date(2026, 10, 7)),
    # 国办发明电〔2026〕10号
    ("元旦", date(2027, 1, 1), date(2027, 1, 3)),
    ("春节", date(2027, 2, 5), date(2027, 2, 13)),
    ("清明节", date(2027, 4, 3), date(2027, 4, 5)),
    ("劳动节", date(2027, 5, 1), date(2027, 5, 5)),
    ("端午节", date(2027, 6, 9), date(2027, 6, 9)),
    ("中秋节", date(2027, 9, 15), date(2027, 9, 15)),
    ("国庆节", date(2027, 10, 1), date(2027, 10, 7)),
)


def next_holiday(today: date) -> Optional[dict]:
    """今天尚未结束的最近一轮法定假。放假期间也算这一轮，不当成已过。"""
    for name, start, end in HOLIDAYS:
        if today > end:
            continue
        days = (end - start).days + 1
        return {
            "name": name,
            "start": start,
            "end": end,
            "days": days,
            "status": "upcoming" if today < start else "today",
        }
    return None
