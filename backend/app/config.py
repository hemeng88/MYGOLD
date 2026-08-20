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

    request_timeout_seconds: float = 15.0


settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
