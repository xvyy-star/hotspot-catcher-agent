"""FastAPI 应用入口。"""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

import redis
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.auth import router as auth_router
from app.api.hotspots import router as hotspots_router
from app.api.knowledge import router as knowledge_router
from app.api.models import router as models_router
from app.api.system import router as system_router
from app.core.config import settings
from app.core.security import AdminAuthAndRateLimitMiddleware
from app.db.session import SessionLocal, engine, init_db
from app.services.model_provider_service import ensure_default_providers
from app.services.scheduler_service import configure_scheduler, run_scheduled_job
from app.services.system_log_service import write_system_log

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def _validate_startup_config() -> None:
    """P0-4: 启动前校验关键安全配置。"""
    issues = settings.validate_for_startup()
    if issues:
        for issue in issues:
            logger.error("[启动校验] %s", issue)
        raise RuntimeError(
            "启动校验未通过，请检查环境变量配置：\n" + "\n".join(f"  - {issue}" for issue in issues)
        )


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    """应用生命周期管理（替代已废弃的 @app.on_event）。"""
    _validate_startup_config()
    init_db()
    with SessionLocal() as db:
        ensure_default_providers(db)
        write_system_log(
            db,
            level="INFO",
            module="startup",
            message="应用启动完成",
            extra={
                "app": settings.app_name,
                "scheduler_enabled": settings.scheduler_enabled,
                "api_auth_enabled": settings.api_auth_enabled,
                "docs_enabled": settings.docs_enabled,
                "auto_create_tables": settings.auto_create_tables,
            },
            commit=True,
        )
    configure_scheduler(scheduler)
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


# P0-8: 生产环境关闭自动文档
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
    lifespan=lifespan,
)

app.state.scheduler = scheduler

app.add_middleware(AdminAuthAndRateLimitMiddleware, api_prefix=settings.api_prefix)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(hotspots_router, prefix=settings.api_prefix)
app.include_router(models_router, prefix=settings.api_prefix)
app.include_router(knowledge_router, prefix=settings.api_prefix)
app.include_router(system_router, prefix=settings.api_prefix)


def scheduled_job() -> None:
    """兼容旧入口：实际逻辑已收敛到 scheduler_service。"""
    run_scheduled_job()


@app.middleware("http")
async def system_exception_logger(request: Request, call_next):  # type: ignore[no-untyped-def]
    """把未捕获异常落到 system_log，前端系统日志页可直接定位。"""
    trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex[:16]
    try:
        response = await call_next(request)
        response.headers.setdefault("X-Trace-Id", trace_id)
        return response
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unhandled request error trace_id=%s path=%s", trace_id, request.url.path)
        try:
            with SessionLocal() as db:
                write_system_log(
                    db,
                    level="ERROR",
                    module="api",
                    message=f"{request.method} {request.url.path} 请求异常：{exc}",
                    trace_id=trace_id,
                    extra={"path": request.url.path, "method": request.method, "query": str(request.url.query)},
                    commit=True,
                )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to persist system error log trace_id=%s", trace_id)
        return JSONResponse(
            status_code=500,
            headers={"X-Trace-Id": trace_id},
            content={"detail": "服务端异常，请在系统日志中按 trace_id 查询。", "trace_id": trace_id},
        )


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}


@app.get("/readyz")
def readyz():
    """生产就绪探针：只有核心依赖可用时才返回 200。

    /health 只代表进程活着；/readyz 代表 MySQL、Redis、Qdrant 等运行依赖可访问。
    部署脚本、容器健康检查和反向代理应优先使用这个接口判断是否可接流量。
    """
    checks: dict[str, dict[str, str | bool]] = {}

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["mysql"] = {"ok": True, "message": "ok"}
    except Exception as exc:  # noqa: BLE001
        checks["mysql"] = {"ok": False, "message": str(exc)}

    try:
        client = redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        checks["redis"] = {"ok": True, "message": "ok"}
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = {"ok": False, "message": str(exc)}

    try:
        response = requests.get(settings.qdrant_url.rstrip("/") + "/", timeout=3)
        response.raise_for_status()
        checks["qdrant"] = {"ok": True, "message": "ok"}
    except Exception as exc:  # noqa: BLE001
        checks["qdrant"] = {"ok": False, "message": str(exc)}

    ok = all(item["ok"] for item in checks.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ready" if ok else "not_ready", "app": settings.app_name, "checks": checks},
    )
