from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "MYGOLD"
    timezone: str = "Asia/Shanghai"
    database_url: str = f"sqlite:///{DATA_DIR / 'mygold.db'}"

    tick_interval_seconds: int = 60
    curve_snapshot_interval_seconds: int = 300
    startup_collect: bool = True

    jd_product_sku: str = "1961543816"
    jd_latest_url: str = (
        "https://api.jdjygold.com/gw2/generic/jrm/h5/m/stdLatestPrice"
    )
    goldmonitor_latest_url: str = "https://jin.20021002.xyz/api.php?type=zs"
    goldmonitor_chart_url: str = "https://jin.20021002.xyz/api.php?action=chart&type=zs"

    request_timeout_seconds: float = 15.0


settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
