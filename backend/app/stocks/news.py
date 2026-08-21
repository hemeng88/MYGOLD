"""拉观察池的公告和市场资讯（东方财富）。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import StockNews, StockQuote
from ..prefs import get_budget
from ..timeutil import now_local
from .classify import classify_title, is_noise
from .universe import active_watchlist

logger = logging.getLogger("mygold.stock_news")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.eastmoney.com/",
}

ANN_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
SEARCH_URL = "https://search-api-web.eastmoney.com/search/jsonp"


def _parse_time(value: str) -> datetime:
    text = (value or "").replace("T", " ").split(".")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19] if " " in text else text[:10], fmt)
        except ValueError:
            continue
    return now_local()


def _search_param(keyword: str, page_index: int = 1, page_size: int = 20) -> str:
    payload = {
        "uid": "",
        "keyword": keyword,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": page_index,
                "pageSize": page_size,
                "preTag": "",
                "postTag": "",
            }
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


async def _fetch_anns(client: httpx.AsyncClient, code: str, pages: int = 1, page_size: int = 20) -> List[Dict]:
    number = code[2:]
    items = []
    for page in range(1, pages + 1):
        response = await client.get(
            ANN_URL,
            params={
                "sr": -1,
                "page_size": page_size,
                "page_index": page,
                "ann_type": "A",
                "client_source": "web",
                "stock_list": number,
                "f_node": 0,
                "s_node": 0,
            },
            headers=HEADERS,
        )
        response.raise_for_status()
        rows = (((response.json() or {}).get("data") or {}).get("list")) or []
        if not rows:
            break
        items.extend(_parse_ann_rows(rows, code, number))
    return items


def _parse_ann_rows(rows, code: str, number: str) -> List[Dict]:
    items = []
    for row in rows:
        title = row.get("title_ch") or row.get("title") or ""
        art = row.get("art_code") or ""
        if not title or not art:
            continue
        tags, score = classify_title(title, market=False)
        items.append(
            {
                "code": code,
                "source": "em_ann",
                "external_id": art,
                "published_at": _parse_time(row.get("notice_date") or row.get("display_time") or ""),
                "title": title[:400],
                "url": "https://data.eastmoney.com/notices/detail/%s/%s.html" % (number, art),
                "kind": "ann",
                "tags": ",".join(tags),
                "score": score,
            }
        )
    return items


async def _fetch_articles(
    client: httpx.AsyncClient, code: str, keyword: str, market: bool, pages: int = 1, page_size: int = 15
) -> List[Dict]:
    items = []
    for page in range(1, pages + 1):
        response = await client.get(
            SEARCH_URL, params={"cb": "a", "param": _search_param(keyword, page, page_size)}, headers=HEADERS
        )
        response.raise_for_status()
        text = response.text
        start, end = text.find("("), text.rfind(")")
        payload = json.loads(text[start + 1 : end]) if start >= 0 and end > start else {}
        rows = ((payload.get("result") or {}).get("cmsArticleWebOld")) or []
        if not rows:
            break
        items.extend(_parse_article_rows(rows, code, market))
    return items


def _parse_article_rows(rows, code: str, market: bool) -> List[Dict]:
    items = []
    for row in rows:
        title = (row.get("title") or "").replace("<em>", "").replace("</em>", "")
        ident = str(row.get("code") or "")
        if not title or not ident:
            continue
        tags, score = classify_title(title, market=market)
        items.append(
            {
                "code": "_market" if market else code,
                "source": "em_news",
                "external_id": ("%s:%s" % (code, ident)) if not market else ident,
                "published_at": _parse_time(row.get("date") or ""),
                "title": title[:400],
                "url": row.get("url") or "",
                "kind": "market" if market else "news",
                "tags": ",".join(tags),
                "score": score,
            }
        )
    return items


def upsert_news(db: Session, items: List[Dict]) -> int:
    if not items:
        return 0
    keys = {(item["source"], item["external_id"]) for item in items}
    existing = {
        (row.source, row.external_id): row
        for row in db.scalars(
            select(StockNews).where(
                StockNews.source.in_([item[0] for item in keys]),
                StockNews.external_id.in_([item[1] for item in keys]),
            )
        ).all()
    }
    now = now_local()
    written = 0
    for item in items:
        row = existing.get((item["source"], item["external_id"]))
        if row is None:
            row = StockNews(source=item["source"], external_id=item["external_id"])
            db.add(row)
        row.code = item["code"]
        row.published_at = item["published_at"]
        row.title = item["title"]
        row.url = item["url"]
        row.kind = item["kind"]
        row.tags = item["tags"]
        row.score = item["score"]
        row.collected_at = now
        written += 1
    db.commit()
    return written


async def collect_news(db: Session) -> Dict:
    written = 0
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        for keyword in ("沪指",):
            try:
                written += upsert_news(db, await _fetch_articles(client, "_market", keyword, True))
            except Exception:
                logger.exception("拉市场资讯失败 %s", keyword)
                db.rollback()
        for code, name, kind in active_watchlist(db.scalars(select(StockQuote)).all(), get_budget(db)):
            batch: List[Dict] = []
            try:
                batch.extend(await _fetch_articles(client, code, name, False))
            except Exception:
                logger.exception("拉 %s 资讯失败", code)
            if kind == "stock":
                try:
                    batch.extend(await _fetch_anns(client, code))
                except Exception:
                    logger.exception("拉 %s 公告失败", code)
                    db.rollback()
            if batch:
                written += upsert_news(db, batch)
    return {"ok": True, "news": written, "message": "股票资讯写入 %d 条" % written}


def recent_news(db: Session, code: str, days: int = 45, limit: int = 24) -> List[StockNews]:
    since = now_local() - timedelta(days=days)
    own = db.scalars(
        select(StockNews)
        .where(StockNews.code == code, StockNews.published_at >= since)
        .order_by(StockNews.published_at.desc())
        .limit(limit)
    ).all()
    if code == "_market":
        return list(own)
    market = db.scalars(
        select(StockNews)
        .where(StockNews.code == "_market", StockNews.published_at >= since)
        .order_by(StockNews.published_at.desc())
        .limit(8)
    ).all()
    return list(own) + list(market)


def news_lean(rows: List[StockNews]) -> Dict:
    """按时间和公告加权，合成 [-1, 1] 的消息倾向。"""
    now = now_local()
    weighted = []
    for row in rows:
        age = max((now - row.published_at).total_seconds(), 0) / 86400
        if age > 30:
            continue
        decay = 1.0 if age <= 3 else (0.6 if age <= 7 else 0.3)
        kind_w = 1.3 if row.kind == "ann" else (0.8 if row.kind == "market" else 1.0)
        if row.score == 0:
            continue
        weighted.append(row.score * decay * kind_w)
    if not weighted:
        return {"lean": 0.0, "sample": 0, "label": "近期没有方向性消息"}
    lean = sum(weighted) / len(weighted)
    lean = max(-1.0, min(1.0, lean))
    if lean >= 0.25:
        label = "公司/市场消息偏正面"
    elif lean <= -0.25:
        label = "公司/市场消息偏谨慎"
    else:
        label = "消息方向不明显"
    return {"lean": round(lean, 3), "sample": len(weighted), "label": label}


def news_context(db: Session, code: str, days: int = 45) -> Dict:
    rows = recent_news(db, code, days=days, limit=24)
    rows = sorted(
        rows,
        key=lambda row: (
            0 if row.kind == "ann" else 1,
            0 if row.score else 1,
            -(row.published_at.timestamp() if row.published_at else 0),
        ),
    )
    useful = [row for row in rows if row.kind == "ann" or row.score or not is_noise(row.title)]
    summary = news_lean(rows)
    summary["items"] = [
        {
            "title": row.title,
            "url": row.url,
            "kind": row.kind,
            "tags": [tag for tag in (row.tags or "").split(",") if tag],
            "score": row.score,
            "published_at": row.published_at.isoformat(timespec="seconds") if row.published_at else None,
        }
        for row in (useful or rows)[:16]
    ]
    return summary
