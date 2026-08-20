import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .collectors.service import collect_once
from .config import settings
from .database import SessionLocal, backfill_event_tags, ensure_schema
from .routers.api import router as api_router
from .scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("mygold")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_schema()
    backfill_event_tags()
    if settings.startup_collect:
        db = SessionLocal()
        try:
            result = await collect_once(db, include_chart=True)
            logger.info("启动采集：%s", result.message)
        except Exception:
            logger.exception("启动采集失败，将依赖后续定时任务")
            db.rollback()
        finally:
            db.close()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title=settings.app_name, description="浙商积存金每日价格曲线归档", lifespan=lifespan)
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
