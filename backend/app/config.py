from pathlib import Path

from pydantic import Field
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
    # 股票反查基金：RPT_MAIN_ORGHOLDDETAIL + ORG_TYPE=01，能拿到全市场持有该股的基金
    fund_stock_holder_url: str = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    fund_stock_quote_url: str = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    # push2 请求密了会直接断连，留一个镜像和新浪兜底，别让覆盖率忽高忽低
    fund_stock_quote_fallback_url: str = "https://push2delay.eastmoney.com/api/qt/ulist.np/get"
    # 最后一层兜底，只认 A 股和港股
    fund_stock_sina_url: str = "https://hq.sinajs.cn/list="
    # 判断报价属于哪个交易日：上证指数的日 K 只在交易日才有新的一根，
    # 拿最后一根的日期就是 A 股最近一个交易日（盘中那根未走完的也算）。
    # 行情接口本身给不出这个信息 —— f86/f124 返回的是服务器当前时间，收盘后照样往前跑。
    # 三家都是日 K，含义一致，取最大的那个日期。push2his 会像 push2 一样断连，
    # 所以不能只靠东方财富一家，否则拿不到日期就得保守地停掉估算。
    fund_kline_tencent_url: str = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    fund_kline_sina_url: str = (
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    )
    fund_kline_url: str = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    # 用来定交易日的标的：上证指数。东方财富用 secid，另两家用各自的代码写法
    fund_calendar_secid: str = "1.000001"
    fund_calendar_symbol: str = "sh000001"

    # 季报只公示前十大重仓，指数基金会多一些，取 20 行足够覆盖
    fund_holdings_topline: int = 20
    fund_quote_interval_seconds: int = 60
    # 持仓报告超过这个天数就提示已经过期，估算只能当参考
    fund_report_stale_days: int = 150
    # 公示股票仓位低于这个比例就不给估算了：债券基金这类穿透出来的数没有意义
    fund_min_coverage_pct: float = 20.0
    # 涨幅榜每个周期取前几名，再穿透看它们重仓的是什么方向。
    # 榜单列表本身几乎不花时间，成本在逐只拉持仓（约 0.28s/只），
    # 30 只/周期去重后约 100 只，整轮采集半分钟出头，够用也不至于太慢。
    fund_rank_top_n: int = 30
    # 主线股票的判定：该周期榜单里至少这么多只基金共同重仓，才算这条主线的成分。
    # 不能用「聚合出的全部股票」——那样榜单基金自己的持仓全在集合里，
    # 命中权重≈它的披露总仓位，这个榜会退化成涨幅榜本身。
    fund_rank_theme_min_funds: int = 2
    # 每个周期取前几只重仓股当这条主线的代表股，再拿去全市场反查。
    # 反查一只股票约 0.5s，跨周期去重后总量可控。
    fund_theme_stock_n: int = 15
    # 全市场持有榜每个周期最多存几名
    fund_theme_holder_top_n: int = 20

    # 账号密码存在数据库 users 表里。下面两个只在「库里一个账号都没有」时用来建初始账号，
    # 之后改了密码不会被启动流程覆盖回去。
    #
    # bootstrap_password 故意没有默认值：任何写进代码的密码都等于公开密码，
    # 不填就不自动建号，改用 backend/scripts/set_password.py 手动建。
    #
    # 这几个字段显式指定 MYGOLD_ 前缀别名：本项目没有配 env_prefix，
    # 默认 bootstrap_password 读的是 BOOTSTRAP_PASSWORD，太通用容易撞，
    # 而 .env 里既有的 MYGOLD_DOMAIN 是 deploy.sh 在用，保持同一套命名。
    bootstrap_username: str = Field(default="hemeng", validation_alias="MYGOLD_BOOTSTRAP_USERNAME")
    bootstrap_password: str = Field(default="", validation_alias="MYGOLD_BOOTSTRAP_PASSWORD")
    # 令牌签名密钥。留空则在 data/auth_secret 里自动生成一次并复用，登录状态跨重启保留；
    # 想集中管理或多实例共享时才需要在 .env 里显式设置。
    auth_secret: str = Field(default="", validation_alias="MYGOLD_AUTH_SECRET")
    auth_token_days: int = 30

    request_timeout_seconds: float = 15.0


settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
