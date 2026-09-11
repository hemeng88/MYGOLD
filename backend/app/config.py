from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "MYGOLD"
    timezone: str = "Asia/Shanghai"
    database_url: str = f"sqlite:///{DATA_DIR / 'mygold.db'}"

    tick_interval_seconds: int = 20
    curve_snapshot_interval_seconds: int = 180
    startup_collect: bool = True

    # 京东/支付宝代销常见规则：买入 0，卖出 0.4%
    sell_fee_rate: float = 0.004
    move_window_seconds: int = 900
    move_persist_checks: int = 3
    event_cooldown_seconds: int = 1800

    jd_product_sku: str = "1961543816"
    jd_latest_url: str = (
        "https://api.jdjygold.com/gw2/generic/jrm/h5/m/stdLatestPrice"
    )
    goldmonitor_latest_url: str = "https://jin.20021002.xyz/api.php?type=zs"
    goldmonitor_chart_url: str = "https://jin.20021002.xyz/api.php?action=chart&type=zs"
    london_gold_url: str = "https://hq.sinajs.cn/list=hf_XAU,fx_susdcny,fx_susdcnh"
    troy_ounce_grams: float = 31.1034768
    stock_hq_url: str = "https://hq.sinajs.cn/list="
    stock_kline_url: str = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "CN_MarketData.getKLineData"
    )
    stock_quote_interval_seconds: int = 30
    stock_news_interval_seconds: int = 300
    stock_kline_limit: int = 1023
    stock_budget_yuan: float = 15000
    stock_forecast_horizon: int = 3

    # 基金：持仓来自天天基金季报明细，持仓股行情走东方财富（A股/港股同一个接口）
    fund_holdings_url: str = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    fund_info_url: str = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNFInfo"
    fund_search_url: str = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx"
    fund_stock_quote_url: str = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    # push2 请求密了会直接断连，留一个镜像和新浪兜底，别让覆盖率忽高忽低
    fund_stock_quote_fallback_url: str = "https://push2delay.eastmoney.com/api/qt/ulist.np/get"
    # 季报只公示前十大重仓，指数基金会多一些，取 20 行足够覆盖
    fund_holdings_topline: int = 20
    fund_quote_interval_seconds: int = 60
    # 持仓报告超过这个天数就提示已经过期，估算只能当参考
    fund_report_stale_days: int = 150
    # 公示股票仓位低于这个比例就不给估算了：债券基金这类穿透出来的数没有意义
    fund_min_coverage_pct: float = 20.0

    request_timeout_seconds: float = 15.0

    # 事件归因：用沪金连续做长周期代理标的，快讯来自华尔街见闻
    proxy_symbol: str = "AU0"
    proxy_daily_url: str = (
        "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/"
        "var%20_bars=/InnerFuturesNewService.getDailyKLine?symbol=AU0"
    )
    flash_api_url: str = "https://api-one-wscn.awtmt.com/apiv1/content/lives"
    flash_calendar_channel: str = "gold-channel"
    flash_narrative_channel: str = "global-channel"
    # 18:00 之后的快讯归到下一个交易日
    session_cutoff_hour: int = 18
    attribution_window_days: int = 180
    # |日涨跌幅| 超过这个值才算显著波动日
    significant_move_pct: float = 0.4
    # 单日最多取几个主标签
    max_tags_per_day: int = 2
    # 主标签门槛：得分不低于当日最高分的这个比例
    tag_score_ratio: float = 0.6
    flash_page_size: int = 50
    flash_max_pages: int = 90


settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
