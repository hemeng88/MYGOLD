from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "MYGOLD"
    timezone: str = "Asia/Shanghai"
    database_url: str = f"sqlite:///{DATA_DIR / 'mygold.db'}"

    # 基金：持仓来自天天基金季报明细，持仓股行情走东方财富（A股/港股同一个接口）
    fund_holdings_url: str = "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    fund_info_url: str = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNFInfo"
    fund_search_url: str = "https://fundsuggest.eastmoney.com/FundSearch/api/FundSearchAPI.ashx"
    fund_rank_url: str = "https://fund.eastmoney.com/data/rankhandler.aspx"
    fund_stock_quote_url: str = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    # push2 请求密了会直接断连，留一个镜像和新浪兜底，别让覆盖率忽高忽低
    fund_stock_quote_fallback_url: str = "https://push2delay.eastmoney.com/api/qt/ulist.np/get"
    # 最后一层兜底，只认 A 股和港股
    fund_stock_sina_url: str = "https://hq.sinajs.cn/list="

    # 季报只公示前十大重仓，指数基金会多一些，取 20 行足够覆盖
    fund_holdings_topline: int = 20
    fund_quote_interval_seconds: int = 60
    # 持仓报告超过这个天数就提示已经过期，估算只能当参考
    fund_report_stale_days: int = 150
    # 公示股票仓位低于这个比例就不给估算了：债券基金这类穿透出来的数没有意义
    fund_min_coverage_pct: float = 20.0
    # 涨幅榜每个周期取前几名，再穿透看它们重仓的是什么方向
    fund_rank_top_n: int = 10

    request_timeout_seconds: float = 15.0


settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
