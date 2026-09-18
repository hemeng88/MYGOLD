"""把基金阈值事件转发给 OpenClaw，由 OpenClaw 负责投递飞书。"""

from __future__ import annotations

import logging
from typing import Dict

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .analysis.fund_estimate import _load, summarize_fund
from .config import settings
from .models import FundFavorite
from .timeutil import now_local

logger = logging.getLogger("mygold.alerts")


def _direction(pct: float) -> str | None:
    threshold = abs(settings.fund_alert_threshold_pct)
    if threshold <= 0:
        return None
    if pct >= threshold:
        return "up"
    if pct <= -threshold:
        return "down"
    return None


def _post(event: Dict) -> None:
    headers = {"Content-Type": "application/json"}
    if settings.openclaw_webhook_token:
        headers["Authorization"] = "Bearer %s" % settings.openclaw_webhook_token
    # payload 同时带 text 和结构化字段，OpenClaw 可直接转发 text，也可按字段编排消息。
    with httpx.Client(timeout=settings.fund_alert_timeout_seconds) as client:
        response = client.post(settings.openclaw_webhook_url, json=event, headers=headers)
        response.raise_for_status()


def check_fund_alerts(db: Session) -> int:
    """检查所有账号的持仓基金，每次行情刷新达到阈值都会提醒。"""
    if not settings.openclaw_webhook_url or settings.fund_alert_threshold_pct <= 0:
        return 0
    favorites = list(
        db.scalars(
            select(FundFavorite).where(FundFavorite.user_id.is_not(None), FundFavorite.shares.is_not(None), FundFavorite.shares > 0)
        ).all()
    )
    if not favorites:
        return 0
    codes = sorted({row.code for row in favorites})
    holdings, quotes, navs = _load(db, codes)
    today = now_local()
    sent = 0
    for favorite in favorites:
        summary = summarize_fund(
            favorite, holdings.get(favorite.code) or [], quotes, navs.get(favorite.code), today
        )
        pct = summary.get("estimate_pct")
        direction = _direction(pct) if isinstance(pct, (int, float)) and not summary.get("settled") else None
        if not direction:
            continue
        trade_date = next(
            (quotes[row.secid].trade_date for row in holdings.get(favorite.code, []) if row.secid in quotes and quotes[row.secid].trade_date),
            today.date().isoformat(),
        )
        label = "上涨" if direction == "up" else "下跌"
        text = "基金提醒：%s（%s）今日估算%s %+.2f%%，持仓今日估算盈亏 %s 元。" % (
            favorite.name,
            favorite.code,
            label,
            pct,
            "—" if summary.get("today_pnl") is None else "%+.2f" % summary["today_pnl"],
        )
        event = {
            # OpenClaw /hooks/wake 的标准字段；其余字段供自定义映射或日志使用。
            "text": text,
            "mode": "now",
            "type": "mygold.fund_threshold",
            "user_id": favorite.user_id,
            "fund": {"code": favorite.code, "name": favorite.name},
            "trade_date": trade_date,
            "direction": direction,
            "estimate_pct": pct,
            "today_pnl": summary.get("today_pnl"),
            "threshold_pct": settings.fund_alert_threshold_pct,
            "source": "mygold",
        }
        try:
            _post(event)
        except Exception:
            logger.exception("OpenClaw 提醒发送失败：%s %s", favorite.code, direction)
            continue
        sent += 1
    if sent:
        logger.info("已发送 %d 条基金阈值提醒", sent)
    return sent
