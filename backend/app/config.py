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
    london_gold_url: str = "https://hq.sinajs.cn/list=hf_XAU"
    stock_hq_url: str = "https://hq.sinajs.cn/list="
    stock_kline_url: str = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        "CN_MarketData.getKLineData"
    )
    stock_quote_interval_seconds: int = 30
    stock_kline_limit: int = 120

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
