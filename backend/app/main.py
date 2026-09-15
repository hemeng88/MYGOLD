import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import SessionLocal, ensure_schema
from .routers.api import router as api_router
from .scheduler import start_scheduler, stop_scheduler
from .users import count_users, ensure_bootstrap_user

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mygold")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_schema()
    db = SessionLocal()
    try:
        created = ensure_bootstrap_user(db, settings.bootstrap_username, settings.bootstrap_password)
        if created:
            logger.info("库里没有账号，已按 .env 建初始账号 %s", created.username)
        elif count_users(db) == 0:
            # 代码里不放默认密码，所以这里只能提示，不能替用户定一个
            logger.warning(
                "还没有任何账号，登录会一直失败。在 .env 里设 MYGOLD_BOOTSTRAP_PASSWORD 后重启，"
                "或执行：docker compose exec mygold python backend/scripts/set_password.py %s",
                settings.bootstrap_username,
            )
    except Exception:
        logger.exception("初始账号创建失败")
        db.rollback()
    finally:
        db.close()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title=settings.app_name, description="基金实时估值：公示仓位穿透持仓股", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")

frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
