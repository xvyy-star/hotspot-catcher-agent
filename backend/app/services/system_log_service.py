"""系统日志服务。

这层只负责“写入、查询、序列化”，避免 API / pipeline 直接操作 ORM 细节。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import SystemLog
from app.core.time import business_now_naive

VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _normalize_level(level: str | None) -> str:
    value = str(level or "INFO").strip().upper()
    return value if value in VALID_LEVELS else "INFO"


def _normalize_filter_level(level: str | None) -> str | None:
    value = str(level or "").strip().upper()
    return value if value in VALID_LEVELS else None


def system_log_to_dict(row: SystemLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "level": row.level,
        "module": row.module,
        "message": row.message,
        "trace_id": row.trace_id,
        "run_id": row.run_id,
        "extra_json": row.extra_json,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def write_system_log(
    db: Session,
    *,
    level: str = "INFO",
    module: str = "system",
    message: str,
    trace_id: str | None = None,
    run_id: str | None = None,
    extra: dict | list | None = None,
    commit: bool = False,
) -> SystemLog:
    row = SystemLog(
        level=_normalize_level(level),
        module=(module or "system")[:80],
        message=(message or "")[:4000],
        trace_id=trace_id,
        run_id=run_id,
        extra_json=extra,
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    return row


def list_system_logs(
    db: Session,
    *,
    limit: int = 100,
    level: str | None = None,
    module: str | None = None,
    keyword: str | None = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 100), 500))
    stmt = select(SystemLog).order_by(desc(SystemLog.created_at), desc(SystemLog.id)).limit(limit)
    if level:
        normalized_level = _normalize_filter_level(level)
        stmt = stmt.where(SystemLog.level == (normalized_level or "__INVALID_LEVEL__"))
    if module:
        stmt = stmt.where(SystemLog.module == module.strip())
    if keyword:
        pattern = f"%{keyword.strip()}%"
        stmt = stmt.where(
            or_(
                SystemLog.message.like(pattern),
                SystemLog.module.like(pattern),
                SystemLog.run_id.like(pattern),
                SystemLog.trace_id.like(pattern),
            )
        )
    return [system_log_to_dict(row) for row in db.execute(stmt).scalars()]


def _filtered_log_condition(
    *,
    level: str | None = None,
    module: str | None = None,
    keyword: str | None = None,
):
    conditions = []
    if level:
        normalized_level = _normalize_filter_level(level)
        conditions.append(SystemLog.level == (normalized_level or "__INVALID_LEVEL__"))
    normalized_module = (module or "").strip()
    if normalized_module:
        conditions.append(SystemLog.module == normalized_module)
    normalized_keyword = (keyword or "").strip()
    if normalized_keyword:
        pattern = f"%{normalized_keyword}%"
        conditions.append(
            or_(
                SystemLog.message.like(pattern),
                SystemLog.module.like(pattern),
                SystemLog.run_id.like(pattern),
                SystemLog.trace_id.like(pattern),
            )
        )
    return conditions


def count_system_logs(
    db: Session,
    *,
    level: str | None = None,
    module: str | None = None,
    keyword: str | None = None,
) -> int:
    stmt = select(func.count(SystemLog.id))
    for condition in _filtered_log_condition(level=level, module=module, keyword=keyword):
        stmt = stmt.where(condition)
    return int(db.execute(stmt).scalar_one() or 0)


def delete_system_logs(
    db: Session,
    *,
    level: str | None = None,
    module: str | None = None,
    keyword: str | None = None,
) -> int:
    """按筛选条件删除系统日志；无筛选条件时删除全部系统日志。"""
    stmt = delete(SystemLog)
    for condition in _filtered_log_condition(level=level, module=module, keyword=keyword):
        stmt = stmt.where(condition)
    result = db.execute(stmt)
    db.commit()
    return int(result.rowcount or 0)


def get_log_summary(db: Session) -> dict[str, Any]:
    since = business_now_naive() - timedelta(days=1)
    total = db.execute(select(func.count(SystemLog.id))).scalar_one() or 0
    errors_24h = (
        db.execute(
            select(func.count(SystemLog.id)).where(
                SystemLog.created_at >= since,
                SystemLog.level.in_(["ERROR", "CRITICAL"]),
            )
        ).scalar_one()
        or 0
    )
    warning_24h = (
        db.execute(
            select(func.count(SystemLog.id)).where(
                SystemLog.created_at >= since,
                SystemLog.level == "WARNING",
            )
        ).scalar_one()
        or 0
    )
    latest_error = db.execute(
        select(SystemLog)
        .where(SystemLog.level.in_(["ERROR", "CRITICAL"]))
        .order_by(desc(SystemLog.created_at), desc(SystemLog.id))
        .limit(1)
    ).scalar_one_or_none()
    level_rows = db.execute(
        select(SystemLog.level, func.count(SystemLog.id)).group_by(SystemLog.level)
    ).all()
    module_rows = db.execute(
        select(SystemLog.module, func.count(SystemLog.id))
        .group_by(SystemLog.module)
        .order_by(desc(func.count(SystemLog.id)))
        .limit(10)
    ).all()
    return {
        "total": int(total),
        "errors_24h": int(errors_24h),
        "warnings_24h": int(warning_24h),
        "latest_error": system_log_to_dict(latest_error) if latest_error else None,
        "level_counts": {str(level): int(count or 0) for level, count in level_rows},
        "module_counts": [{"module": str(module), "count": int(count or 0)} for module, count in module_rows],
    }
