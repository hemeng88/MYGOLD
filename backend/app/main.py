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
from .users import claim_orphan_favorites, count_users, ensure_bootstrap_user

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
        # 加账号之前的收藏没有归属，系统里只有一个账号时认领给它
        claimed = claim_orphan_favorites(db)
        if claimed:
            logger.info("已把 %d 条旧收藏归到唯一账号名下", claimed)
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


@app.middleware("http")
async def cache_headers(request, call_next):
    """index.html 禁缓存，带 hash 的静态资源长期缓存。

    Vite 产物的 JS/CSS 文件名带内容 hash，可以放心长缓存；但 index.html 不能，
    它一旦被缓存住，手机上就会一直加载旧版前端 —— 部署了也看不到变化，
    加了登录也跳不到登录页。这个坑已经踩过几次，所以在这里显式修掉。
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif path == "/" or path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache"
    return response


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
