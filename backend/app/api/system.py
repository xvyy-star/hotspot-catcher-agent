"""系统状态、系统日志与运维看板 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.services.deployment_check_service import get_deployment_readiness
from app.services.system_log_service import count_system_logs, delete_system_logs, list_system_logs
from app.services.system_metrics_service import get_system_metrics

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status")
def system_status() -> dict:
    """无需鉴权的轻量状态，用于前端初始化登录配置。"""
    return {
        "data": {
            "app": settings.app_name,
            "api_auth_enabled": settings.api_auth_enabled,
            "admin_username": settings.admin_username,
            "admin_display_name": settings.admin_display_name,
            "rate_limit_enabled": settings.rate_limit_enabled,
            "cors_origins": list(settings.cors_origins),
        }
    }


@router.get("/logs")
def system_logs(
    limit: int = Query(100, ge=1, le=500),
    level: str | None = Query(None),
    module: str | None = Query(None),
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    """系统日志列表，供前端运维日志页排查启动、任务和接口异常。"""
    return {
        "data": list_system_logs(
            db,
            limit=limit,
            level=level,
            module=module,
            keyword=keyword,
        )
    }


@router.delete("/logs")
def delete_logs(
    level: str | None = Query(None),
    module: str | None = Query(None),
    keyword: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    """按筛选条件批量删除系统日志；无筛选条件则删除全部。"""
    before_count = count_system_logs(db, level=level, module=module, keyword=keyword)
    deleted_count = delete_system_logs(db, level=level, module=module, keyword=keyword)
    has_filter = bool((level or "").strip() or (module or "").strip() or (keyword or "").strip())
    return {
        "ok": True,
        "data": {
            "deleted_count": deleted_count,
            "matched_count": before_count,
            "scope": "filtered" if has_filter else "all",
        },
    }


@router.get("/metrics")
def system_metrics(db: Session = Depends(get_db)) -> dict:
    """轻量数据看板指标，避免前端重复拼多个低层接口。"""
    return {"data": get_system_metrics(db)}


@router.get("/readiness")
def deployment_readiness(db: Session = Depends(get_db)) -> dict:
    """上线交付就绪检查：汇总安全、数据真实性、采集源、模型和运维风险。"""
    return {"data": get_deployment_readiness(db)}
