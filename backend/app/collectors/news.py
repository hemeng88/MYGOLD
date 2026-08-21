import logging
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

import httpx

from ..config import settings

logger = logging.getLogger("mygold.news")

KEYWORDS = (
    ("美联储", 8),
    ("降息", 7),
    ("加息", 7),
    ("非农", 7),
    ("cpi", 6),
    ("美元", 5),
    ("汇率", 5),
    ("美元指数", 6),
    ("石油", 5),
    ("原油", 6),
    ("油价", 5),
    ("避险", 6),
    ("黄金", 5),
    ("金价", 6),
    ("金市", 4),
    ("中东", 6),
    ("地缘", 5),
    ("战争", 6),
    ("突破", 4),
    ("暴涨", 5),
    ("暴跌", 5),
    ("伦敦金", 4),
    ("现货黄金", 5),
    ("实际利率", 6),
    ("国债", 3),
    ("就业", 4),
    ("通胀", 5),
    ("boj", 4),
    ("欧央行", 4),
)

# 「金市」只在没有宏观标签时作为兜底。
TAG_RULES = (
    ("汇率", ("汇率", "美元指数", "离岸人民币", "在岸人民币", "dxy", "usd/cny", "人民币中间价", "美元兑", "人民币汇率", "强美元", "弱美元")),
    ("石油", ("石油", "原油", "油价", "opec", "wti", "布伦特", "brent")),
    ("通胀", ("通胀", "通货膨胀", "cpi", "ppi", "pce", "物价")),
    ("就业", ("非农", "失业率", "就业", "adp", "初请失业")),
    ("地缘", ("中东", "地缘", "战争", "冲突", "伊朗", "以色列", "霍尔木兹")),
    ("利率", ("国债", "实际利率", "收益率", "十年期", "美债")),
)
FED_CORE = ("美联储", "鲍威尔", "fomc", "powell", "federal reserve", "联储主席", "联邦公开市场")
FED_SOFT = ("降息", "加息", "利率决议")
OTHER_BANK = ("欧央行", "欧洲央行", "日央行", "日本央行", "boj", "人民银行", "央行购金", "黄金储备")
GOLD_KEYS = ("黄金", "金价", "现货黄金", "伦敦金", "comex", "积存金", "金市")


def _has(blob: str, keys: tuple) -> bool:
    return any(key.lower() in blob for key in keys)


def classify_tags(text: str, limit: int = 3) -> List[str]:
    blob = (text or "").lower()
    tags: List[str] = []
    if _has(blob, FED_CORE) or (_has(blob, FED_SOFT) and not _has(blob, OTHER_BANK)):
        tags.append("美联储")
    if _has(blob, OTHER_BANK):
        tags.append("央行")
    tags.extend(name for name, keys in TAG_RULES if _has(blob, keys) and name not in tags)
    if not tags and _has(blob, GOLD_KEYS):
        tags = ["金市"]
    return (tags or ["其他"])[:limit]


# 以下规则只服务事件归因：比 classify_tags 严格得多，宁可漏掉也不要噪音。
# 每天固定出现的栏目、公司财报、无关小国数据都会被挡掉，否则它们会淹没真正的信号。
MACRO_EXCLUDE = (
    "早餐",
    "午报",
    "晚报",
    "收评",
    "复盘",
    "盘前",
    "一图",
    "直播",
    "尾盘",
    "盘初",
    "亚市",
    "隔夜逆回购",
    "RRP",
    "财报",
    "业绩",
    "净利润",
    "营业收入",
    "钻井数",
    # 放宽地缘关键词后涌进来的行情播报，本身不含事件信息
    "播报",
    "股市",
)
# 只认对金价真正有分量的经济体
MAJOR = ("美国", "美联储", "欧元区", "中国")
MACRO_RULES = (
    # (标签, 关键词, 是否要求主要经济体)
    ("美联储", ("美联储", "fomc", "鲍威尔", "点阵图", "联邦公开市场", "利率决策"), False),
    ("通胀", ("cpi", "pce", "ppi", "通胀预期", "通货膨胀"), True),
    ("就业", ("非农", "adp", "初请失业", "失业率", "就业人数"), True),
    ("石油", ("opec", "原油库存", "布伦特", "wti", "油价", "原油产量"), False),
    ("央行", ("欧洲央行", "欧央行", "日本央行", "日央行", "英格兰银行", "英央行", "央行购金", "黄金储备"), False),
    ("汇率", ("美元指数", "离岸人民币", "在岸人民币", "人民币中间价", "人民币汇率"), False),
    ("利率", ("美债收益率", "国债收益率", "实际利率"), False),
    # 地缘不能只列中东：8/20 那波急涨前的「胡塞袭击沙特」「乌军袭击俄能源设施」
    # 都因为不含指定地名被整条丢掉，升级判定根本看不到它们
    (
        "地缘",
        (
            "伊朗", "以色列", "霍尔木兹", "中东", "以军", "德黑兰", "地缘",
            "加沙", "哈马斯", "真主党", "黎巴嫩", "叙利亚", "内塔尼亚胡",
            "胡塞", "也门", "沙特", "红海", "苏伊士",
            "俄乌", "乌克兰", "俄军", "乌军", "基辅", "普京", "泽连斯基",
            "朝鲜", "台海", "委内瑞拉", "制裁", "停火", "战争",
        ),
        False,
    ),
)
# 收益率、汇率这类每天都在动，只有出现明显异动的说法才算事件
MOVE_WORDS = ("飙升", "暴跌", "大涨", "大跌", "跳升", "跳水", "突破", "跌破", "新高", "新低", "创下")
NEEDS_MOVE = ("利率", "汇率")


def classify_macro_tags(text: str, limit: int = 3) -> List[str]:
    """给事件归因用的严格分类。命中不了就返回空，调用方直接丢弃。"""
    raw = text or ""
    blob = raw.lower()
    if any(word in raw for word in MACRO_EXCLUDE):
        return []
    tags: List[str] = []
    for tag, keys, needs_major in MACRO_RULES:
        if not any(key in blob for key in keys):
            continue
        if needs_major and not any(area in raw for area in MAJOR):
            continue
        if tag in NEEDS_MOVE and not any(word in raw for word in MOVE_WORDS):
            continue
        tags.append(tag)
    return tags[:limit]


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/xml, */*",
}


def _score(text: str) -> int:
    blob = (text or "").lower()
    return sum(weight for key, weight in KEYWORDS if key.lower() in blob)


def _item(title: str, url: str = "", source: str = "", summary: str = "") -> Dict[str, str]:
    return {
        "headline": (title or "").strip()[:300],
        "url": (url or "").strip()[:500],
        "source": (source or "").strip()[:64],
        "summary": (summary or title or "").strip()[:800],
    }


async def _from_cls(client: httpx.AsyncClient) -> List[Dict[str, str]]:
    url = "https://www.cls.cn/nodeapi/updateTelegraphList"
    response = await client.get(
        url,
        params={"app": "CailianpressWeb", "os": "web", "sv": "8.4.6", "rn": 30},
        headers=HEADERS,
    )
    response.raise_for_status()
    body = response.json()
    rows = (((body.get("data") or {}).get("roll_data")) or body.get("data") or [])
    items = []
    for row in rows:
        title = row.get("title") or row.get("brief") or row.get("content") or ""
        if not title:
            continue
        items.append(
            _item(
                title=title,
                url=row.get("shareurl") or row.get("url") or "https://www.cls.cn/telegraph",
                source="财联社",
                summary=row.get("brief") or row.get("content") or title,
            )
        )
    return items


async def _from_sina(client: httpx.AsyncClient) -> List[Dict[str, str]]:
    url = "https://feed.mix.sina.com.cn/api/roll/get"
    response = await client.get(
        url,
        params={"pageid": "153", "lid": "2516", "num": 20, "page": 1},
        headers=HEADERS,
    )
    response.raise_for_status()
    body = response.json()
    rows = ((body.get("result") or {}).get("data")) or []
    items = []
    for row in rows:
        title = row.get("title") or ""
        if not title:
            continue
        items.append(
            _item(
                title=title,
                url=row.get("url") or "",
                source="新浪财经",
                summary=row.get("intro") or title,
            )
        )
    return items


async def _from_google_news(client: httpx.AsyncClient) -> List[Dict[str, str]]:
    url = "https://news.google.com/rss/search"
    response = await client.get(
        url,
        params={
            "q": "黄金 金价 美联储 原油 汇率",
            "hl": "zh-CN",
            "gl": "CN",
            "ceid": "CN:zh-Hans",
        },
        headers=HEADERS,
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    items = []
    for node in root.findall(".//item")[:20]:
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        desc = (node.findtext("description") or "").strip()
        if title:
            items.append(_item(title, link, "Google新闻", desc))
    return items


async def fetch_leading_event() -> Optional[Dict[str, str]]:
    timeout = httpx.Timeout(min(settings.request_timeout_seconds, 8.0))
    fetchers = (_from_cls, _from_sina, _from_google_news)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for fetcher in fetchers:
            try:
                items = await fetcher(client)
            except Exception:
                logger.exception("新闻源失败：%s", fetcher.__name__)
                continue
            ranked = [item for item in items if item.get("headline")]
            if not ranked:
                continue
            ranked.sort(key=lambda item: _score("%s %s" % (item["headline"], item.get("summary") or "")), reverse=True)
            top = ranked[0]
            if _score("%s %s" % (top["headline"], top.get("summary") or "")) <= 0:
                goldish = [item for item in ranked if _score(item["headline"]) > 0]
                top = goldish[0] if goldish else ranked[0]
            return top
    return None
