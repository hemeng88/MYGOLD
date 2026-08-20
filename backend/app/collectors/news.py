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
            "q": "黄金 金价 美联储",
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
