"""把基金阈值事件转发给 OpenClaw，由 OpenClaw 负责投递飞书。"""

from __future__ import annotations

import logging
from sqlalchemy import select
from sqlalchemy.orm import Session

from .analysis.fund_estimate import _load, summarize_fund
from .config import settings
from .models import FundAlertState, FundFavorite
from .notify import notify
from .timeutil import now_local

logger = logging.getLogger("mygold.alerts")


async def check_fund_alerts(db: Session) -> int:
    """检查所有账号的持仓基金，累计偏离上次成功提醒达到阈值才提醒。"""
    if (
        not settings.openclaw_webhook_url
        or not settings.openclaw_webhook_token
        or not settings.openclaw_target
        or settings.fund_alert_threshold_pct <= 0
    ):
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
    user_ids = {row.user_id for row in favorites if row.user_id is not None}
    states = {
        (row.user_id, row.fund_code): row
        for row in db.scalars(
            select(FundAlertState).where(
                FundAlertState.user_id.in_(user_ids),
                FundAlertState.fund_code.in_(codes),
            )
        ).all()
    } if user_ids else {}
    today = now_local()
    sent = 0
    for favorite in favorites:
        summary = summarize_fund(
            favorite, holdings.get(favorite.code) or [], quotes, navs.get(favorite.code), today
        )
        pct = summary.get("estimate_pct")
        if not isinstance(pct, (int, float)) or summary.get("settled"):
            continue
        trade_date = next(
            (quotes[row.secid].trade_date for row in holdings.get(favorite.code, []) if row.secid in quotes and quotes[row.secid].trade_date),
            today.date().isoformat(),
        )
        state_key = (favorite.user_id, favorite.code)
        state = states.get(state_key)
        baseline = state.last_estimate_pct if state and state.trade_date == trade_date else 0.0
        delta = float(pct) - baseline
        if abs(delta) < abs(settings.fund_alert_threshold_pct):
            continue
        label = "上涨" if delta > 0 else "下跌"
        text = "基金提醒：%s（%s）较上次提醒%s %+.2f 个百分点" % (
            favorite.name, favorite.code, label, delta
        )
        body = "代码 %s · 交易日 %s · 估算涨跌 %+.2f%% · 持仓今日估算盈亏 %s 元" % (
            favorite.code,
            trade_date,
            pct,
            "—" if summary.get("today_pnl") is None else "%+.2f" % summary["today_pnl"],
        )
        if await notify(text, body=body):
            if state is None:
                state = FundAlertState(
                    user_id=favorite.user_id,
                    fund_code=favorite.code,
                    trade_date=trade_date,
                    last_estimate_pct=float(pct),
                    updated_at=now_local(),
                )
                db.add(state)
                states[state_key] = state
            else:
                state.trade_date = trade_date
                state.last_estimate_pct = float(pct)
                state.updated_at = now_local()
            db.commit()
            sent += 1
    if sent:
        logger.info("已发送 %d 条基金阈值提醒", sent)
    return sent
