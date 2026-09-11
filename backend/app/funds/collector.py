"""基金数据落库：季报持仓、官方净值、持仓股实时报价。

持仓一个季度才变一次，所以走每日一次的定时任务；持仓股报价才是开盘时要一直刷的，
和 A 股观察池那条链路分开跑，互相不影响。
"""

from __future__ import annotations

import logging
from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FundFavorite, FundHolding, FundNav, FundStockQuote
from ..timeutil import now_local
from . import sources
from .favorites import list_codes

logger = logging.getLogger("mygold.funds")


def upsert_holdings(db: Session, fund_code: str, holdings: List[Dict]) -> int:
    if not holdings:
        return 0
    existing = {
        row.secid: row
        for row in db.scalars(select(FundHolding).where(FundHolding.fund_code == fund_code)).all()
    }
    keep = set()
    written = 0
    for item in holdings:
        secid = item["secid"]
        keep.add(secid)
        row = existing.get(secid)
        if row is None:
            row = FundHolding(fund_code=fund_code, secid=secid)
            db.add(row)
        row.stock_code = item["stock_code"]
        row.stock_name = item.get("stock_name")
        row.market = item["market"]
        row.weight_pct = item["weight_pct"]
        row.rank = item.get("rank")
        row.report_date = item["report_date"] or ""
        row.source = item.get("source") or "em_f10_jjcc"
        row.updated_at = now_local()
        written += 1
    # 换季之后掉出前十大的股票要删掉，不然权重会重复计算
    for secid, row in existing.items():
        if secid not in keep:
            db.delete(row)
    db.commit()
    return written


def upsert_navs(db: Session, rows: List[Dict]) -> int:
    if not rows:
        return 0
    written = 0
    for item in rows:
        row = db.get(FundNav, item["code"])
        if row is None:
            row = FundNav(code=item["code"])
            db.add(row)
        for key, value in item.items():
            setattr(row, key, value)
        written += 1
    db.commit()
    return written


def upsert_stock_quotes(db: Session, quotes: List[Dict]) -> int:
    if not quotes:
        return 0
    existing = {
        row.secid: row
        for row in db.scalars(
            select(FundStockQuote).where(FundStockQuote.secid.in_([item["secid"] for item in quotes]))
        ).all()
    }
    written = 0
    for item in quotes:
        row = existing.get(item["secid"])
        if row is None:
            row = FundStockQuote(secid=item["secid"])
            db.add(row)
        for key, value in item.items():
            setattr(row, key, value)
        written += 1
    db.commit()
    return written


def held_secids(db: Session) -> List[str]:
    codes = list_codes(db)
    if not codes:
        return []
    return list(
        db.scalars(select(FundHolding.secid).where(FundHolding.fund_code.in_(codes)).distinct()).all()
    )


def collect_fund_holdings(db: Session) -> Dict:
    codes = list_codes(db)
    if not codes:
        return {"ok": True, "holdings": 0, "message": "还没收藏基金"}
    written = 0
    failed: List[str] = []
    for code in codes:
        try:
            parsed = sources.fetch_holdings(code)
            written += upsert_holdings(db, code, parsed["holdings"])
        except Exception:
            logger.exception("拉 %s 持仓失败", code)
            db.rollback()
            failed.append(code)
    pruned = prune_stock_quotes(db)
    message = "基金持仓写入 %d 条" % written
    if failed:
        message += "，%d 只没取到（%s）" % (len(failed), ",".join(failed))
    if pruned:
        message += "，清掉 %d 条没人用的报价" % pruned
    return {"ok": written > 0, "holdings": written, "message": message}


def prune_stock_quotes(db: Session) -> int:
    """取消收藏或者换季掉出重仓后，报价缓存里的孤儿行没人用了，顺手清掉。"""
    keep = set(held_secids(db))
    removed = 0
    for row in db.scalars(select(FundStockQuote)).all():
        if row.secid not in keep:
            db.delete(row)
            removed += 1
    if removed:
        db.commit()
    return removed


def collect_fund_navs(db: Session) -> Dict:
    codes = list_codes(db)
    if not codes:
        return {"ok": True, "navs": 0, "message": ""}
    rows = sources.fetch_fund_info(codes)
    written = upsert_navs(db, rows)
    # 基金改名或者收藏时没拿到全名的，顺手补一下
    for item in rows:
        favorite = db.get(FundFavorite, item["code"])
        if favorite and item.get("name") and favorite.name != item["name"]:
            favorite.name = item["name"]
    db.commit()
    return {"ok": written > 0, "navs": written, "message": "基金净值 %d 只" % written}


def collect_fund_quotes(db: Session) -> Dict:
    secids = held_secids(db)
    if not secids:
        return {"ok": True, "quotes": 0, "message": "没有持仓股要刷"}
    quotes = sources.fetch_stock_quotes(secids)
    written = upsert_stock_quotes(db, quotes)
    return {"ok": written > 0, "quotes": written, "message": "持仓股报价 %d 只" % written}


def sync_fund(db: Session, code: str) -> Dict:
    """新收藏一只基金时立刻补齐持仓、净值和报价，省得等定时任务。"""
    result = {"holdings": 0, "navs": 0, "quotes": 0}
    messages: List[str] = []
    try:
        parsed = sources.fetch_holdings(code)
        result["holdings"] = upsert_holdings(db, code, parsed["holdings"])
        if not parsed["holdings"]:
            messages.append("这只基金暂时查不到公示持仓")
    except Exception as exc:
        logger.exception("同步 %s 持仓失败", code)
        db.rollback()
        messages.append("持仓没取到：%s" % exc)
    try:
        result["navs"] = upsert_navs(db, sources.fetch_fund_info([code]))
    except Exception as exc:
        logger.exception("同步 %s 净值失败", code)
        db.rollback()
        messages.append("净值没取到：%s" % exc)
    try:
        secids = list(
            db.scalars(select(FundHolding.secid).where(FundHolding.fund_code == code).distinct()).all()
        )
        if secids:
            result["quotes"] = upsert_stock_quotes(db, sources.fetch_stock_quotes(secids))
    except Exception as exc:
        logger.exception("同步 %s 持仓股报价失败", code)
        db.rollback()
        messages.append("报价没取到：%s" % exc)
    result["message"] = "；".join(messages)
    return result


def refresh_funds(db: Session, include_holdings: bool = True) -> Dict:
    holdings_result = {"holdings": 0, "message": ""}
    nav_result = {"navs": 0, "message": ""}
    quote_result = {"quotes": 0, "message": ""}
    if include_holdings:
        try:
            holdings_result = collect_fund_holdings(db)
        except Exception as exc:
            logger.exception("基金持仓刷新失败")
            db.rollback()
            holdings_result = {"holdings": 0, "message": "持仓失败：%s" % exc}
    try:
        nav_result = collect_fund_navs(db)
    except Exception as exc:
        logger.exception("基金净值刷新失败")
        db.rollback()
        nav_result = {"navs": 0, "message": "净值失败：%s" % exc}
    try:
        quote_result = collect_fund_quotes(db)
    except Exception as exc:
        logger.exception("持仓股报价刷新失败")
        db.rollback()
        quote_result = {"quotes": 0, "message": "报价失败：%s" % exc}
    return {
        "ok": bool(quote_result.get("quotes") or nav_result.get("navs")),
        "holdings": holdings_result.get("holdings") or 0,
        "navs": nav_result.get("navs") or 0,
        "quotes": quote_result.get("quotes") or 0,
        "message": "；".join(
            part
            for part in (
                holdings_result.get("message"),
                nav_result.get("message"),
                quote_result.get("message"),
            )
            if part
        ),
    }
