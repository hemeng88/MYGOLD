"""基金外部数据源：天天基金季报持仓 + 东方财富持仓股行情。

持仓来自 fundf10 的 `type=jjcc` 接口，返回的是 JSONP 包着一段 HTML 表格，
所以这里只能按标签硬解。行情走 push2 的 ulist.np，secid 里已经带了市场号，
A 股和港股一次请求就能一起取到，不用像观察池那样区分新浪代码前缀。
"""

from __future__ import annotations

import logging
import re
from typing import Dict, Iterable, List, Optional

import httpx

from ..config import settings
from ..timeutil import now_local

logger = logging.getLogger("mygold.funds")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://fundf10.eastmoney.com/",
}
EM_QUOTE_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Referer": "https://quote.eastmoney.com/",
}
FUND_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Referer": "https://fund.eastmoney.com/",
}
# 新浪 hq 不带 Referer 会 403，返回体还是 GBK
SINA_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Referer": "https://finance.sina.com.cn/",
}

# 一次报价请求塞多少个 secid，持仓股多的时候分批发
QUOTE_BATCH = 100

MARKET_LABEL = {
    "0": "深",
    "1": "沪",
    "105": "美",
    "106": "美",
    "107": "美",
    "116": "港",
    "153": "美",
}

_HQ_LINE = re.compile(r'hq_str_([a-z]{2}\d+)="([^"]*)"')
_CONTENT = re.compile(r'content:"(.*)",arryear', re.S)
_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
_SECID = re.compile(r"quote\.eastmoney\.com/unify/r/(\d+)\.([0-9A-Za-z]+)")
_STOCK_NAME = re.compile(r"<td class='tol'>.*?>([^<>]+)</a>", re.S)
_REPORT_DATE = re.compile(r"截止至：<font[^>]*>([\d-]{8,10})</font>")
_TOR_CELL = re.compile(r"<td class='tor'>(.*?)</td>", re.S)
_RANK = re.compile(r"^\s*<td>(\d+)</td>")
_TAG = re.compile(r"<[^>]+>")


def _num(value) -> Optional[float]:
    try:
        if value is None:
            return None
        text = str(value).replace(",", "").replace("%", "").strip()
        if text in ("", "-", "--", "—"):
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _strip_tags(html: str) -> str:
    return _TAG.sub("", html).replace("&nbsp;", " ").strip()


def market_label(market: str) -> str:
    return MARKET_LABEL.get(str(market), "其他")


def report_label(report_date: Optional[str]) -> Optional[str]:
    """2026-06-30 -> 2026年2季度。"""
    if not report_date or len(report_date) < 7:
        return None
    try:
        year = int(report_date[:4])
        month = int(report_date[5:7])
    except ValueError:
        return None
    return "%d年%d季度" % (year, (month + 2) // 3)


def _parse_holdings_row(row_html: str) -> Optional[Dict]:
    hit = _SECID.search(row_html)
    if not hit:
        return None
    market, stock_code = hit.group(1), hit.group(2)
    # 最新价/涨跌幅那两格是空 span 靠 JS 填的，所以第一个带 % 的右对齐格就是占净值比例
    weight = None
    for cell in _TOR_CELL.findall(row_html):
        text = _strip_tags(cell)
        if text.endswith("%"):
            weight = _num(text)
            break
    if weight is None or weight <= 0:
        return None
    name_hit = _STOCK_NAME.search(row_html)
    rank_hit = _RANK.search(row_html)
    return {
        "secid": "%s.%s" % (market, stock_code),
        "market": market,
        "stock_code": stock_code,
        "stock_name": _strip_tags(name_hit.group(1)) if name_hit else None,
        "weight_pct": weight,
        "rank": int(rank_hit.group(1)) if rank_hit else None,
    }


def parse_holdings(text: str) -> Dict:
    """从 jjcc 响应里挑出报告期最新的那一块持仓。"""
    body = _CONTENT.search(text or "")
    if not body:
        return {"report_date": None, "holdings": []}
    content = body.group(1)
    blocks = re.split(r"<div class='boxitem", content)[1:]
    best: Dict = {"report_date": None, "holdings": []}
    for block in blocks:
        date_hit = _REPORT_DATE.search(block)
        report_date = date_hit.group(1) if date_hit else None
        rows: List[Dict] = []
        seen = set()
        for row_html in _ROW.findall(block):
            item = _parse_holdings_row(row_html)
            if not item or item["secid"] in seen:
                continue
            seen.add(item["secid"])
            rows.append(item)
        if not rows:
            continue
        # 同一次响应里会带好几个季度，只要最新的那个报告期
        if best["report_date"] is None or (report_date or "") > (best["report_date"] or ""):
            best = {"report_date": report_date, "holdings": rows}
    return best


def fetch_holdings(code: str) -> Dict:
    """拉一只基金最新一期的股票持仓明细。"""
    with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
        response = client.get(
            settings.fund_holdings_url,
            params={
                "type": "jjcc",
                "code": code,
                "topline": settings.fund_holdings_topline,
                "year": "",
                "month": "",
                "rt": 0,
            },
            headers=HEADERS,
        )
        response.raise_for_status()
        response.encoding = response.encoding or "utf-8"
        text = response.text
    parsed = parse_holdings(text)
    for item in parsed["holdings"]:
        item["fund_code"] = code
        item["report_date"] = parsed["report_date"]
        item["source"] = "em_f10_jjcc"
        item["updated_at"] = now_local()
    return parsed


def fetch_fund_info(codes: Iterable[str]) -> List[Dict]:
    """基金名称 + 官方最新净值。"""
    wanted = [str(code) for code in codes if code]
    if not wanted:
        return []
    with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
        response = client.get(
            settings.fund_info_url,
            params={
                "pageIndex": 1,
                "pageSize": max(len(wanted), 1),
                "plat": "Android",
                "appType": "ttjj",
                "product": "EFund",
                "Fcodes": ",".join(wanted),
                "deviceid": "1",
                "version": "6.2.8",
                "Uid": "",
            },
            headers=FUND_HEADERS,
        )
        response.raise_for_status()
    rows = (response.json() or {}).get("Datas") or []
    now = now_local()
    out: List[Dict] = []
    for row in rows:
        code = str(row.get("FCODE") or "").strip()
        if not code:
            continue
        out.append(
            {
                "code": code,
                "name": (row.get("SHORTNAME") or "").strip() or None,
                "nav": _num(row.get("NAV")),
                "acc_nav": _num(row.get("ACCNAV")),
                "nav_date": (row.get("PDATE") or None),
                "nav_chg_pct": _num(row.get("NAVCHGRT")),
                "source": "em_fundmob",
                "collected_at": now,
            }
        )
    return out


def search_funds(keyword: str, limit: int = 12) -> List[Dict]:
    """按代码或名称模糊找基金，给收藏页做候选。"""
    query = (keyword or "").strip()
    if not query:
        return []
    with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
        response = client.get(
            settings.fund_search_url,
            params={"m": 1, "key": query, "_": 1},
            headers=FUND_HEADERS,
        )
        response.raise_for_status()
    rows = (response.json() or {}).get("Datas") or []
    out: List[Dict] = []
    for row in rows:
        code = str(row.get("CODE") or "").strip()
        if not code.isdigit() or len(code) != 6:
            continue
        # 搜「白酒」会连中证白酒这种指数一起返回，代码也是 6 位，靠 CATEGORY 才能筛掉
        if str(row.get("CATEGORY") or "") != "700":
            continue
        base = row.get("FundBaseInfo") or {}
        out.append(
            {
                "code": code,
                "name": (row.get("NAME") or base.get("SHORTNAME") or "").strip() or code,
                "fund_type": (base.get("FTYPE") or None),
                "nav": _num(base.get("DWJZ")),
                "nav_date": base.get("FSRQ") or None,
            }
        )
        if len(out) >= limit:
            break
    return out


def _sina_code(secid: str) -> Optional[str]:
    """secid -> 新浪代码。新浪只兜底 A 股和港股，美股先不管。"""
    market, _, code = str(secid).partition(".")
    if market == "1":
        return "sh" + code
    if market == "0":
        return "sz" + code
    if market == "116":
        return "hk" + code
    return None


def _parse_sina_line(sina_code: str, payload: str, now) -> Optional[Dict]:
    parts = payload.split(",")
    if sina_code.startswith("hk"):
        # 港股：0 英文名, 1 中文名, 3 昨收, 6 现价
        if len(parts) < 9:
            return None
        name, prev, price = parts[1], _num(parts[3]), _num(parts[6])
    else:
        # A 股：0 名称, 2 昨收, 3 现价
        if len(parts) < 4:
            return None
        name, prev, price = parts[0], _num(parts[2]), _num(parts[3])
    if price is None or price <= 0:
        return None
    change_pct = round((price - prev) / prev * 100, 3) if prev else None
    return {
        "code": sina_code[2:],
        "name": (name or "").strip() or None,
        "price": price,
        "prev_close": prev,
        "change_pct": change_pct,
        "source": "sina_hq",
        "collected_at": now,
    }


def _quote_sina(secids: List[str], now) -> List[Dict]:
    by_sina = {}
    for secid in secids:
        sina_code = _sina_code(secid)
        if sina_code:
            by_sina[sina_code] = secid
    if not by_sina:
        return []
    out: List[Dict] = []
    codes = sorted(by_sina)
    with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
        for start in range(0, len(codes), QUOTE_BATCH):
            batch = codes[start : start + QUOTE_BATCH]
            try:
                response = client.get(settings.fund_stock_sina_url + ",".join(batch), headers=SINA_HEADERS)
                response.raise_for_status()
                text = response.content.decode("gbk", errors="ignore")
            except Exception:
                logger.exception("新浪兜底报价失败（%d 只）", len(batch))
                continue
            for match in _HQ_LINE.finditer(text):
                sina_code, payload = match.group(1), match.group(2)
                secid = by_sina.get(sina_code)
                if not secid:
                    continue
                item = _parse_sina_line(sina_code, payload, now)
                if not item:
                    continue
                item["secid"] = secid
                item["market"] = secid.split(".")[0]
                out.append(item)
    return out


def _quote_batch(client: httpx.Client, url: str, batch: List[str], now) -> List[Dict]:
    response = client.get(
        url,
        params={
            "fltt": 2,
            "invt": 2,
            "fields": "f2,f3,f12,f13,f14,f18",
            "secids": ",".join(batch),
        },
        headers=EM_QUOTE_HEADERS,
    )
    response.raise_for_status()
    rows = (((response.json() or {}).get("data") or {}).get("diff")) or []
    out: List[Dict] = []
    for row in rows:
        code = str(row.get("f12") or "").strip()
        market = str(row.get("f13") if row.get("f13") is not None else "").strip()
        if not code or not market:
            continue
        out.append(
            {
                "secid": "%s.%s" % (market, code),
                "code": code,
                "market": market,
                "name": (row.get("f14") or None),
                "price": _num(row.get("f2")),
                "prev_close": _num(row.get("f18")),
                "change_pct": _num(row.get("f3")),
                "source": "em_ulist",
                "collected_at": now,
            }
        )
    return out


# 天天基金排行榜：sc 是排序字段，对应 datas 里第几列都对不上，只能各自记住
# datas 每行是逗号分隔：0代码 1简称 3日期 4单位净值 5累计净值 6日增长率
#                      8近1月 9近3月 10近6月 11近1年 14今年来
RANK_PERIODS = {
    "1yzf": ("近1月", 8),
    "3yzf": ("近3月", 9),
    "6yzf": ("近6月", 10),
    "1nzf": ("近1年", 11),
    "jnzf": ("今年来", 14),
}
_RANK_DATAS = re.compile(r"datas:\[(.*?)\],allRecords", re.S)
_RANK_ROW = re.compile(r'"([^"]+)"')


def fetch_rankings(period: str, limit: int = 10) -> List[Dict]:
    """按周期拉公募基金涨幅榜。period 取 RANK_PERIODS 里的键。"""
    if period not in RANK_PERIODS:
        raise ValueError("不认识的周期：%s" % period)
    _label, index = RANK_PERIODS[period]
    with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
        response = client.get(
            settings.fund_rank_url,
            params={
                "op": "ph",
                "dt": "kf",
                "ft": "all",
                "rs": "",
                "gs": 0,
                "sc": period,
                "st": "desc",
                "pi": 1,
                "pn": max(limit, 1),
            },
            headers={**FUND_HEADERS, "Referer": "https://fund.eastmoney.com/data/fundranking.html"},
        )
        response.raise_for_status()
        text = response.text
    body = _RANK_DATAS.search(text)
    if not body:
        return []
    out: List[Dict] = []
    for raw in _RANK_ROW.findall(body.group(1)):
        parts = raw.split(",")
        if len(parts) <= index:
            continue
        code = parts[0].strip()
        gain = _num(parts[index])
        if not code or gain is None:
            continue
        out.append(
            {
                "code": code,
                "name": (parts[1] or "").strip() or code,
                "return_pct": gain,
                "nav": _num(parts[4]) if len(parts) > 4 else None,
                "nav_date": (parts[3] or "").strip() or None,
                "rank": len(out) + 1,
            }
        )
        if len(out) >= limit:
            break
    return out


def fetch_stock_fund_holders(stock_code: str, report_date: str, limit: int = 800) -> List[Dict]:
    """反查：某只股票被全市场哪些基金持有。

    和 type=jjcc 正好相反 —— 那个是「基金 -> 它的重仓股」，只能覆盖我们主动去拉的基金；
    这个是「股票 -> 持有它的基金」，一次就能拿到全市场（热门股上千只）。

    关键字段 NETVALUE_RATIO 是该股占这只基金净值的比例，正好当权重用。
    ORG_TYPE="01" 是基金，不加会混进保险、社保、券商等其它机构。
    """
    if not stock_code or not report_date:
        return []
    with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
        response = client.get(
            settings.fund_stock_holder_url,
            params={
                "sortColumns": "NETVALUE_RATIO",
                "sortTypes": "-1",
                "pageSize": limit,
                "pageNumber": 1,
                "reportName": "RPT_MAIN_ORGHOLDDETAIL",
                "columns": "SECURITY_CODE,HOLDER_NAME,FUND_CODE,NETVALUE_RATIO,FUND_TYPE",
                "filter": '(SECURITY_CODE="%s")(REPORT_DATE=\'%s\')(ORG_TYPE="01")'
                % (stock_code, report_date),
            },
            headers={**FUND_HEADERS, "Referer": "https://data.eastmoney.com/zlsj/"},
        )
        response.raise_for_status()
    payload = response.json() or {}
    rows = ((payload.get("result") or {}).get("data")) or []
    out: List[Dict] = []
    for row in rows:
        code = str(row.get("FUND_CODE") or "").strip()
        ratio = _num(row.get("NETVALUE_RATIO"))
        if not code or ratio is None or ratio <= 0:
            continue
        out.append(
            {
                "stock_code": str(row.get("SECURITY_CODE") or "").strip(),
                "fund_code": code,
                "fund_name": (row.get("HOLDER_NAME") or "").strip() or None,
                "fund_type": (row.get("FUND_TYPE") or "").strip() or None,
                # 占该基金净值的比例，百分数
                "netvalue_ratio": ratio,
            }
        )
    return out


def fetch_stock_quotes(secids: Iterable[str]) -> List[Dict]:
    """按 secid 批量取持仓股行情。

    push2 请求一密就会直接断连，丢一批就能让覆盖率掉几十个点、估算跟着失真，
    所以按 push2 -> push2delay 镜像 -> 新浪 依次兜底，每一轮只补上一轮没取到的。
    新浪只认 A 股和港股，美股取不到就让 covered_pct 老实反映出来。
    """
    wanted = sorted({str(secid) for secid in secids if secid})
    if not wanted:
        return []
    now = now_local()
    found: Dict[str, Dict] = {}
    for url in (settings.fund_stock_quote_url, settings.fund_stock_quote_fallback_url):
        missing = [secid for secid in wanted if secid not in found]
        if not missing:
            break
        with httpx.Client(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
            for start in range(0, len(missing), QUOTE_BATCH):
                batch = missing[start : start + QUOTE_BATCH]
                try:
                    for item in _quote_batch(client, url, batch, now):
                        found.setdefault(item["secid"], item)
                except Exception:
                    logger.warning("%s 这批报价没取到（%d 只），换下一个源", url, len(batch))
    missing = [secid for secid in wanted if secid not in found]
    if missing:
        for item in _quote_sina(missing, now):
            found.setdefault(item["secid"], item)
    still = [secid for secid in wanted if secid not in found]
    if still:
        logger.warning("%d 只持仓股所有源都没取到：%s", len(still), ",".join(still[:10]))
    return list(found.values())
