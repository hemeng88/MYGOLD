"""当前候选的财务、行业与市场检查；不回填到历史技术策略收益中。"""
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from copy import deepcopy
from datetime import date, timedelta
import math
import threading
import time

import httpx

from ..timeutil import now_local, from_unix_seconds
from ..market_session import should_poll_quotes
from . import research, universe

FINANCE_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"
_cache = {}
_lock = threading.Lock()


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _get(url, params):
    with httpx.Client(timeout=5, headers=universe.SINA_HEADERS) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()


def _cached(key, ttl, load):
    with _lock:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < cached[1]:
            return deepcopy(cached[2])
    try:
        result = load()
        if not result:
            raise ValueError("empty data")
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
        result, ttl = None, 60
    with _lock:
        # 固定上限，避免长期运行因代码/板块增加导致无限增长。
        if len(_cache) >= 1000:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (time.monotonic(), ttl, deepcopy(result))
    return result


def financial_rows(code):
    def load():
        payload = _get(FINANCE_URL, {
            "reportName": "RPT_LICO_FN_CPD", "columns": "ALL",
            "filter": '(SECURITY_CODE="%s")' % code,
            "pageSize": 8, "pageNumber": 1, "sortColumns": "REPORTDATE",
            "sortTypes": "-1", "source": "WEB", "client": "WEB",
        })
        if payload.get("success") is not True:
            raise ValueError("financial source unavailable")
        rows = (payload.get("result") or {}).get("data")
        if not isinstance(rows, list):
            raise ValueError("invalid financial rows")
        return [row for row in rows if isinstance(row, dict) and row.get("SECURITY_CODE") == code]
    return _cached(("finance", code, now_local().date().isoformat()), 21600, load) or []


def quote(secid):
    def load():
        payload = _get(QUOTE_URL, {"secid": secid, "fltt": 2, "invt": 2,
                                    "fields": "f57,f58,f86,f127,f164,f167,f170,f198"})
        data = payload.get("data")
        if not isinstance(data, dict) or data.get("f57") != secid.split(".")[-1]:
            raise ValueError("quote security mismatch")
        return data
    return _cached(("quote", secid), 240, load) or {}


def industry_members(code):
    def load():
        payload = _get(FINANCE_URL, {
            "reportName": "RPT_LICO_FN_CPD",
            "columns": "SECURITY_CODE,BOARD_CODE,BOARD_NAME,NOTICE_DATE",
            "filter": '(BOARD_CODE="%s")(ISNEW="1")' % code,
            "pageSize": 500, "pageNumber": 1, "source": "WEB", "client": "WEB",
        })
        result = payload.get("result") or {}
        rows = result.get("data")
        if payload.get("success") is not True or not isinstance(rows, list) or result.get("pages") != 1:
            raise ValueError("incomplete industry membership")
        if result.get("count") != len(rows) or any(row.get("BOARD_CODE") != code for row in rows):
            raise ValueError("industry membership mismatch")
        return rows
    return _cached(("members", code, now_local().date().isoformat()), 21600, load) or []


def fundamentals(rows, today=None):
    today = today or now_local().date()
    valid = []
    for row in rows:
        report, notice = day(row.get("REPORTDATE")), day(row.get("NOTICE_DATE"))
        # 源只有公告日期；当天公告从次日才采用，避免把盘后公告提前用于盘中。
        if report and notice and report <= notice < today:
            valid.append(row)
    if not valid:
        return {"status": "unknown", "label": "财报待核实", "reasons": ["没有可核实披露日期的财报"],
                "source": "东方财富业绩报表"}
    row = max(valid, key=lambda value: (value["REPORTDATE"], value["NOTICE_DATE"]))
    result = {"report_date": str(row["REPORTDATE"])[:10], "notice_date": str(row["NOTICE_DATE"])[:10],
              "revenue_yoy_pct": number(row.get("YSTZ")), "profit_yoy_pct": number(row.get("SJLTZ")),
              "net_profit": number(row.get("PARENT_NETPROFIT")), "roe_pct": number(row.get("WEIGHTAVG_ROE")),
              "industry_name": row.get("BOARD_NAME") or row.get("PUBLISHNAME"),
              "industry_code": row.get("BOARD_CODE"), "source": "东方财富业绩报表"}
    reasons = []
    stale = (today - day(result["report_date"])).days > 200
    missing = any(result[key] is None for key in ("revenue_yoy_pct", "profit_yoy_pct", "net_profit", "roe_pct"))
    if stale:
        reasons.append("报告期距今超过200天")
    if missing:
        reasons.append("盈利或增长指标缺失")
    for key, threshold, text in [("net_profit", 0, "归母净利润非正"), ("roe_pct", 0, "加权ROE非正")]:
        if result[key] is not None and result[key] <= threshold:
            reasons.append(text)
    for key, text in [("revenue_yoy_pct", "营业收入同比下降"), ("profit_yoy_pct", "归母净利润同比下降")]:
        if result[key] is not None and result[key] < 0:
            reasons.append(text)
    result.update(status="unknown" if stale or missing else "risk" if reasons else "pass",
                  label="财报待核实" if stale or missing else "基本面需谨慎" if reasons else "基本面初筛通过",
                  reasons=reasons or ["归母净利润与ROE为正，营业收入和归母净利润同比均未下降"])
    return result


def market_context(items, histories, trade_date, complete, mode="intraday"):
    today = now_local().date()
    changes = [row["change_pct"] for row in items]
    count = len(changes)
    breadth = sum(value > 0 for value in changes) / count * 100 if count else None
    mean = sum(changes) / count if count else None
    cutoff = (today + timedelta(days=1 if mode == "close" else 0)).isoformat()
    bars = research.clean_bars(histories.get("sh000300") or [], cutoff)
    stats = research.features(bars)
    result = {"status": "unknown", "label": "大盘数据待核实", "advance_pct": round(breadth, 2) if breadth is not None else None,
              "mean_change_pct": round(mean, 3) if mean is not None else None,
              "stock_count": count, "trade_date": trade_date, "index_as_of": stats["as_of"] if stats else None,
              "index_close": stats["last"] if stats else None, "ma20": stats["ma20"] if stats else None,
              "ma60": stats["ma60"] if stats else None, "source": "新浪全A股有效报价 / 腾讯沪深300完整日线",
              "reason": "需要完整扫描、至少100只有效报价及近期沪深300日线；非当日行情仅供参考"}
    if not complete or count < 100 or not stats or trade_date != today.isoformat():
        return result
    if (today - day(stats["as_of"])).days > 10:
        return result
    bearish = stats["last"] < stats["ma60"] and stats["ma20"] < stats["ma60"]
    bullish = stats["last"] > stats["ma20"] >= stats["ma60"]
    weak = bearish or breadth < 35
    result.update(status="weak" if weak else "favorable" if bullish and breadth >= 55 else "neutral",
                  label="大盘偏弱" if weak else "大盘偏强" if bullish and breadth >= 55 else "大盘震荡",
                  reason="沪深300低于60日均价且20日均价低于60日均价，或全市场上涨家数占比低于35%，判为偏弱；趋势向上且上涨占比至少55%判为偏强，其余为震荡")
    return result


def industry_context(profile, financial, sector, market):
    name = profile.get("f127") or financial.get("industry_name")
    change = number(sector.get("f170"))
    timestamp = number(sector.get("f86"))
    observed = None
    if timestamp and timestamp > 0:
        try:
            observed = from_unix_seconds(timestamp)
        except (ValueError, OverflowError, OSError):
            pass
    baseline = market.get("mean_change_pct")
    result = {"status": "unknown", "label": "行业待核实", "name": name,
              "method": "行业指数",
              "change_pct": change, "relative_pct": None,
              "as_of": observed.isoformat() if observed else None, "source": "东方财富行业指数 / 新浪全A等权涨跌幅",
              "reason": "需要匹配行业指数、行情日期及有效市场基准"}
    if not name or name != sector.get("f58") or change is None or baseline is None or not observed:
        return result
    if observed.date().isoformat() != market.get("trade_date") or observed > now_local():
        return result
    if should_poll_quotes() and (now_local() - observed).total_seconds() > 1200:
        result["reason"] = "行业行情在交易时段已超过20分钟，暂不用于优先观察"
        return result
    if market.get("status") == "unknown":
        return result
    relative = change - baseline
    passed = change >= 0 and relative >= 0
    result.update(status="pass" if passed else "weak", label="行业当日偏强" if passed else "行业当日偏弱",
                  relative_pct=round(relative, 3), reason="行业当日涨幅非负且不低于全A有效报价等权平均涨幅才通过；这是当日强弱，不代表中长期行业趋势")
    return result


def peer_context(financial, members, market_items, market, exclude_code):
    """指数不可用时的同业样本；不冒充行业指数，排除候选自身。"""
    today = now_local().date()
    eligible = {row["SECURITY_CODE"] for row in members
                if day(row.get("NOTICE_DATE")) and day(row["NOTICE_DATE"]) < today
                and row.get("BOARD_NAME") == financial.get("industry_name")
                and row.get("SECURITY_CODE") != exclude_code}
    peers = [row for row in market_items if row["code"] in eligible]
    count, total = len(peers), len(eligible)
    coverage = count / total if total else 0
    change = sum(row["change_pct"] for row in peers) / count if count else None
    baseline = market.get("mean_change_pct")
    relative = change - baseline if change is not None and baseline is not None else None
    usable = count >= 5 and coverage >= 0.8 and market.get("status") != "unknown" and relative is not None
    passed = usable and change >= 0 and relative >= 0
    return {"status": "pass" if passed else "weak" if usable else "unknown",
            "label": "同业样本当日偏强" if passed else "同业样本当日偏弱" if usable else "同业样本不足",
            "name": financial.get("industry_name"), "method": "同业等权样本（指数备用）",
            "change_pct": round(change, 3) if change is not None else None,
            "relative_pct": round(relative, 3) if usable else None, "as_of": None,
            "sample_count": count, "member_count": total, "coverage_pct": round(coverage * 100, 2),
            "source": "东方财富最新财报行业分类 / 本轮新浪全A有效报价",
            "reason": "行业指数不可用，改用同行业已披露财报成分的当日等权涨跌（排除本股）；至少5只且覆盖80%才判断强弱。只用本轮快照，个股报价日期未逐只验证，不等同完整行业指数。"}


def _parallel(keys, loader, timeout):
    output = {}
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="stock-factors")
    futures = {pool.submit(loader, key): key for key in keys}
    try:
        for future in as_completed(futures, timeout=timeout):
            try:
                output[futures[future]] = future.result()
            except Exception:
                output[futures[future]] = None
    except TimeoutError:
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return output


def enrich(items, market_items, histories, trade_date, complete, mode="intraday"):
    market = market_context(market_items, histories, trade_date, complete, mode=mode)

    def load(item):
        financial = fundamentals(financial_rows(item))
        if financial.get("industry_code") and financial.get("industry_name"):
            profile = {"f127": financial["industry_name"], "f198": financial["industry_code"]}
        else:
            profile = quote(universe.secid_of(item))
        return financial, profile

    details = _parallel([row["code"] for row in items], load, 40)
    codes = set()
    for detail in details.values():
        if detail:
            financial, profile = detail
            code = profile.get("f198") or financial.get("industry_code")
            if isinstance(code, str) and code.startswith("BK") and code[2:].isdigit():
                codes.add(code)
    def load_sector(code):
        index_quote = quote("90." + code)
        return {"quote": index_quote, "members": [] if index_quote else industry_members(code)}
    sectors = _parallel(codes, load_sector, 25)
    for item in items:
        financial, profile = details.get(item["code"]) or (fundamentals([]), {})
        code = profile.get("f198") or financial.get("industry_code")
        data = sectors.get(code) or {}
        sector = data.get("quote") or {}
        industry = industry_context(profile, financial, sector, market)
        if not sector:
            industry = peer_context(financial, data.get("members") or [], market_items, market, item["code"])
        blockers = []
        if financial["status"] != "pass":
            blockers.extend(financial["reasons"])
        if industry["status"] != "pass":
            blockers.append(industry["label"])
        if market["status"] in ("weak", "unknown"):
            blockers.append(market["label"])
        technical = item.get("priority_eligible") is True
        item["technical_priority_eligible"] = technical
        item["priority_eligible"] = technical and not blockers
        item["factors"] = {"fundamentals": financial, "industry": industry,
                           "blockers": blockers, "passed": not blockers}
        if blockers:
            item["status"] = "多因子待确认"
    return {"market": market, "checked": len(items),
            "passed": sum(row["factors"]["passed"] for row in items),
            "priority_count": sum(row["priority_eligible"] for row in items),
            "note": "基本面、行业与大盘仅检查本轮最多20只技术候选；未通过或缺数据保留展示，但禁止AI标为优先观察。历史事件收益仅验证原有技术规则，不包含新增因子；新增规则未经组合回测。"}
