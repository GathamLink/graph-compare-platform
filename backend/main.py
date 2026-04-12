import logging
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

from database import engine, Base
from routers import tasks, images, diff, report

# ─────────────────────────────────────────────
# 初始化数据库表
# ─────────────────────────────────────────────
Base.metadata.create_all(bind=engine)

# ─────────────────────────────────────────────
# 数据库迁移：自动添加新列（兼容已有数据库）
# ─────────────────────────────────────────────
def _migrate_db():
    """
    SQLite 不支持 ALTER TABLE DROP COLUMN，但支持 ADD COLUMN。
    此函数在每次启动时检查是否有缺失列，有则自动添加，保证向前兼容。
    """
    with engine.connect() as conn:
        from sqlalchemy import text
        # 检查 tasks 表是否已有 pair_mode / diff_algo 列
        result = conn.execute(text("PRAGMA table_info(tasks)"))
        columns = {row[1] for row in result}
        if "pair_mode" not in columns:
            conn.execute(text(
                "ALTER TABLE tasks ADD COLUMN pair_mode VARCHAR(20) NOT NULL DEFAULT 'sequential'"
            ))
            conn.commit()
        if "diff_algo" not in columns:
            conn.execute(text(
                "ALTER TABLE tasks ADD COLUMN diff_algo VARCHAR(20) NOT NULL DEFAULT 'balanced'"
            ))
            conn.commit()

        # images 表迁移
        img_cols_res = conn.execute(text("PRAGMA table_info(images)"))
        img_cols = {row[1] for row in img_cols_res.fetchall()}
        if "thumb_oss_key" not in img_cols:
            conn.execute(text("ALTER TABLE images ADD COLUMN thumb_oss_key VARCHAR(512)"))
            conn.commit()

        # diff_results 表迁移
        diff_cols_res = conn.execute(text("PRAGMA table_info(diff_results)"))
        diff_cols = {row[1] for row in diff_cols_res.fetchall()}
        if "is_similar" not in diff_cols:
            conn.execute(text("ALTER TABLE diff_results ADD COLUMN is_similar BOOLEAN"))
            conn.commit()

_migrate_db()

# ─────────────────────────────────────────────
# FastAPI 实例
# ─────────────────────────────────────────────
app = FastAPI(
    title="Graph Compare Platform API",
    description="图片对比平台后端接口",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─────────────────────────────────────────────
# CORS
# ─────────────────────────────────────────────
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:13010").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────
# 访问日志中间件
# ─────────────────────────────────────────────
import time
import datetime
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

# 按天写入 access 日志文件
def _access_log(msg: str):
    today = datetime.date.today().strftime("%Y-%m-%d")
    log_dir = os.path.join(os.path.dirname(__file__), "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"access.{today}.log")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(msg + "\n")
    # 维护软链 access.log → 当天文件（macOS/Linux）
    link = os.path.join(log_dir, "access.log")
    try:
        if os.path.islink(link) or os.path.exists(link):
            os.remove(link)
        os.symlink(os.path.abspath(log_path), link)
    except Exception:
        pass

# 跳过不需要记录的路径
_ACCESS_SKIP = {"/", "/docs", "/redoc", "/openapi.json", "/health"}

class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        # 跳过静态/健康检查路由
        if request.url.path in _ACCESS_SKIP:
            return await call_next(request)

        t0 = time.time()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        method = request.method
        path   = request.url.path
        query  = str(request.url.query) if request.url.query else "-"

        # 读取请求 body（只对写操作读，且截断至 500 字符）
        body_summary = "-"
        if method in ("POST", "PUT", "PATCH"):
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    raw = await request.body()
                    body_str = raw.decode("utf-8", errors="replace")
                    body_summary = body_str[:500] + ("…" if len(body_str) > 500 else "")
                except Exception:
                    body_summary = "<read error>"
            elif "multipart/form-data" in content_type:
                body_summary = "<multipart/form-data>"

        response = await call_next(request)

        elapsed_ms = int((time.time() - t0) * 1000)
        status = response.status_code

        # 状态前缀：4xx/5xx 标记
        status_tag = "OK " if status < 400 else ("ERR" if status >= 500 else "WRN")

        line = (
            f"{now} [{status_tag}] {method} {path}"
            f"  query={query}"
            f"  body={body_summary}"
            f"  status={status}"
            f"  elapsed={elapsed_ms}ms"
        )
        _access_log(line)
        return response

app.add_middleware(AccessLogMiddleware)

# ─────────────────────────────────────────────
# 全局异常处理
# ─────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": "服务器内部错误", "detail": str(exc)},
    )

# ─────────────────────────────────────────────
# 路由注册
# ─────────────────────────────────────────────
API_PREFIX = "/api/v1"
app.include_router(tasks.router, prefix=API_PREFIX)
app.include_router(images.router, prefix=API_PREFIX)
app.include_router(diff.router, prefix=API_PREFIX)
app.include_router(report.router, prefix=API_PREFIX)

# ─────────────────────────────────────────────
# 健康检查
# ─────────────────────────────────────────────
@app.get("/health", tags=["system"])
def health_check():
    from services.oss_service import is_minio_available
    return {
        "status": "ok",
        "minio": "ok" if is_minio_available() else "unavailable",
    }

@app.get("/", tags=["system"])
def root():
    return {"message": "Graph Compare Platform API", "docs": "/docs"}


# ─────────────────────────────────────────────
# 入口（直接 python main.py 时使用）
# ─────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("BACKEND_PORT", "13011"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
