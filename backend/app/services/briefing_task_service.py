"""早报异步任务服务。

同步生成接口在本地演示没问题，但上线后会遇到几个典型问题：
- 采集源、LLM、RAG、推送任一环节变慢都会让 HTTP 请求长时间阻塞。
- 浏览器或反向代理超时后，用户不知道任务到底有没有继续跑。
- 用户重复点击容易制造并发任务。

这里用轻量后台线程先把“提交任务 / 查询状态 / 任务完成后刷新”的产品闭环补齐。
后续真正企业部署时，可以把这层替换成 Celery / RQ / Dramatiq / 云队列。
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.runner import run_daily_briefing
from app.core.config import settings
from app.db.models import AgentRun
from app.db.session import SessionLocal
from app.services.scheduler_service import briefing_lock_key, maybe_enqueue_briefing_knowledge_ingest
from app.services.session_service import get_redis
from app.services.system_log_service import write_system_log
from app.storage.repository import create_run, finish_run

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"SUCCESS", "FAILED", "SKIPPED"}
ACTIVE_STATUSES = {"QUEUED", "RUNNING"}
_RELEASE_SLOT_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


def _safe_trigger(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)[:24] or "manual"


def _new_run_id(trigger: str, target_date: date) -> str:
    return f"{_safe_trigger(trigger)}-async-{target_date.isoformat()}-{uuid.uuid4().hex[:8]}"


def _slot_key(target_date: date) -> str:
    return briefing_lock_key(target_date)


def _claim_generation_slot(target_date: date, run_id: str) -> tuple[bool, str | None]:
    """原子占用同日生成槽，返回 (是否成功, 已占用的 run_id)。"""
    client = get_redis()
    ttl = max(60, int(settings.briefing_task_lock_seconds))
    key = _slot_key(target_date)
    if client.set(key, run_id, nx=True, ex=ttl):
        return True, None
    existing = client.get(key)
    return False, str(existing) if existing else None


def _release_generation_slot(target_date: date, run_id: str) -> None:
    """仅释放属于当前任务的生成槽，避免误删后来任务的锁。"""
    try:
        get_redis().eval(_RELEASE_SLOT_SCRIPT, 1, _slot_key(target_date), run_id)
    except Exception:  # noqa: BLE001
        logger.warning("释放早报生成槽失败 run_id=%s", run_id, exc_info=True)


def _iso(value: Any) -> str | None:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value) if value is not None else None


def _progress_for_status(status: str, meta: dict[str, Any] | None = None) -> int:
    status = str(status or "").upper()
    meta = meta or {}
    if status == "QUEUED":
        return 8
    if status == "RUNNING":
        return int(meta.get("progress") or 45)
    if status == "SUCCESS":
        return 100
    if status == "FAILED":
        return 100
    if status == "SKIPPED":
        return 100
    return 0


def run_to_task_dict(row: AgentRun | None) -> dict[str, Any] | None:
    if not row:
        return None
    meta = row.meta if isinstance(row.meta, dict) else {}
    return {
        "id": row.id,
        "run_id": row.run_id,
        "status": row.status,
        "progress": _progress_for_status(row.status, meta),
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "total_raw": row.total_raw,
        "total_events": row.total_events,
        "error_message": row.error_message,
        "meta": meta,
        "target_date": meta.get("target_date"),
        "trigger": meta.get("trigger"),
        "mode": meta.get("mode"),
        "knowledge_ingest": meta.get("knowledge_ingest"),
        "message": meta.get("reason")
        or (meta.get("api_result", {}).get("message") if isinstance(meta.get("api_result"), dict) else None),
    }


def get_briefing_task_status(db: Session, run_id: str) -> dict[str, Any] | None:
    row = db.execute(select(AgentRun).where(AgentRun.run_id == run_id)).scalar_one_or_none()
    return run_to_task_dict(row)


def _merge_run_meta(db: Session, run_id: str, patch: dict[str, Any]) -> None:
    row = db.execute(select(AgentRun).where(AgentRun.run_id == run_id)).scalar_one_or_none()
    if not row:
        return
    row.meta = {**(row.meta or {}), **patch}
    db.commit()


def _worker(*, run_id: str, target_date: date, trigger: str, knowledge_trigger: str) -> None:
    with SessionLocal() as db:
        try:
            _merge_run_meta(db, run_id, {"progress": 18, "running_at": datetime.utcnow().isoformat()})
            result = run_daily_briefing(
                db,
                target_date=target_date,
                trigger=trigger,
                run_id=run_id,
                initial_meta={
                    "mode": "async",
                    "trigger": trigger,
                    "target_date": target_date.isoformat(),
                    "progress": 25,
                },
            )
            data = result.model_dump(mode="json")
            if data.get("status") == "SUCCESS":
                knowledge_ingest = maybe_enqueue_briefing_knowledge_ingest(
                    db,
                    run_id=run_id,
                    target_date=target_date,
                    trigger=knowledge_trigger,
                )
                if knowledge_ingest:
                    data["knowledge_ingest"] = knowledge_ingest
            current_row = db.execute(select(AgentRun).where(AgentRun.run_id == run_id)).scalar_one_or_none()
            current_meta = current_row.meta if current_row and isinstance(current_row.meta, dict) else {}
            _merge_run_meta(
                db,
                run_id,
                {
                    **current_meta,
                    "mode": "async",
                    "trigger": trigger,
                    "target_date": target_date.isoformat(),
                    "progress": 100,
                    "api_result": {
                        "status": data.get("status"),
                        "message": data.get("message"),
                        "total_events": data.get("total_events")
                        or len(((data.get("briefing") or {}).get("events") or [])),
                    },
                    "knowledge_ingest": data.get("knowledge_ingest"),
                    "async_finished_at": datetime.utcnow().isoformat(),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("异步早报任务失败 run_id=%s", run_id)
            db.rollback()
            finish_run(
                db,
                run_id,
                "FAILED",
                error_message=str(exc),
                meta={
                    "mode": "async",
                    "trigger": trigger,
                    "target_date": target_date.isoformat(),
                    "progress": 100,
                    "async_finished_at": datetime.utcnow().isoformat(),
                },
            )
            db.commit()


def _worker_with_slot(*, run_id: str, target_date: date, trigger: str, knowledge_trigger: str) -> None:
    try:
        _worker(
            run_id=run_id,
            target_date=target_date,
            trigger=trigger,
            knowledge_trigger=knowledge_trigger,
        )
    finally:
        _release_generation_slot(target_date, run_id)


def _record_skipped_submission(
    *,
    run_id: str,
    target_date: date,
    trigger: str,
    queued_at: str,
    reason: str,
) -> dict[str, Any]:
    """Persist a terminal task so every returned run_id remains pollable."""
    with SessionLocal() as db:
        create_run(
            db,
            run_id,
            status="QUEUED",
            meta={
                "mode": "async",
                "trigger": trigger,
                "target_date": target_date.isoformat(),
                "progress": 8,
                "queued_at": queued_at,
            },
        )
        finish_run(
            db,
            run_id,
            "SKIPPED",
            meta={
                "mode": "async",
                "trigger": trigger,
                "target_date": target_date.isoformat(),
                "progress": 100,
                "reason": reason,
            },
        )
        db.commit()
        task = get_briefing_task_status(db, run_id) or {}
    return {**task, "reused": True, "message": reason}


def enqueue_briefing_generation(
    *,
    target_date: date,
    trigger: str = "manual",
    knowledge_trigger: str | None = None,
) -> dict[str, Any]:
    """提交早报异步生成任务并立即返回 run_id。"""
    run_id = _new_run_id(trigger, target_date)
    queued_at = datetime.utcnow().isoformat()

    claimed, existing_run_id = _claim_generation_slot(target_date, run_id)
    if not claimed and not existing_run_id:
        # The previous owner may have released the key between SET NX and GET.
        # Retry once; proceeding without a confirmed claim would allow duplicates.
        claimed, existing_run_id = _claim_generation_slot(target_date, run_id)
        if not claimed and not existing_run_id:
            return _record_skipped_submission(
                run_id=run_id,
                target_date=target_date,
                trigger=trigger,
                queued_at=queued_at,
                reason="早报任务锁状态正在变化，本次提交已跳过，请稍后重试。",
            )

    if not claimed and existing_run_id:
        with SessionLocal() as db:
            existing_task = get_briefing_task_status(db, existing_run_id)
        if existing_task and str(existing_task.get("status") or "").upper() in ACTIVE_STATUSES:
            return {
                **existing_task,
                "reused": True,
                "message": "同一天已有早报任务在执行，已复用原任务，避免重复采集和模型调用。",
            }

        # A competing async request may observe the Redis claim just before its
        # QUEUED row is committed. Its run_id is still safe to poll shortly.
        if not existing_task and "-async-" in existing_run_id:
            task = {
                "run_id": existing_run_id,
                "status": "QUEUED",
                "progress": 8,
                "target_date": target_date.isoformat(),
                "trigger": trigger,
            }
            return {
                **task,
                "reused": True,
                "message": "同一天已有早报任务在执行，已复用原任务，避免重复采集和模型调用。",
            }

        if not existing_task:
            # The shared lock belongs to the scheduler/task-center entry point,
            # whose lock token is intentionally not an AgentRun id. Record this
            # request as a terminal task so the frontend can poll it normally.
            return _record_skipped_submission(
                run_id=run_id,
                target_date=target_date,
                trigger=trigger,
                queued_at=queued_at,
                reason="同一天已有调度任务在执行，本次提交已跳过。",
            )

        # 终态任务不应继续占用 Redis 槽；释放后再尝试一次。
        _release_generation_slot(target_date, existing_run_id)
        claimed, existing_run_id = _claim_generation_slot(target_date, run_id)
        if not claimed:
            if not existing_run_id or "-async-" not in existing_run_id:
                return _record_skipped_submission(
                    run_id=run_id,
                    target_date=target_date,
                    trigger=trigger,
                    queued_at=queued_at,
                    reason="早报任务锁已被其他入口占用，本次提交已跳过。",
                )
            return {
                "run_id": existing_run_id,
                "status": "QUEUED",
                "progress": 8,
                "target_date": target_date.isoformat(),
                "trigger": trigger,
                "reused": True,
                "message": "早报任务正在创建，已复用当前任务。",
            }

    with SessionLocal() as db:
        try:
            create_run(
                db,
                run_id,
                status="QUEUED",
                meta={
                    "mode": "async",
                    "trigger": trigger,
                    "target_date": target_date.isoformat(),
                    "progress": 8,
                    "queued_at": queued_at,
                },
            )
            write_system_log(
                db,
                level="INFO",
                module="briefing-task",
                message="早报异步任务已入队",
                run_id=run_id,
                extra={"target_date": target_date.isoformat(), "trigger": trigger},
            )
            db.commit()
        except Exception:
            _release_generation_slot(target_date, run_id)
            raise

    thread = threading.Thread(
        target=_worker_with_slot,
        kwargs={
            "run_id": run_id,
            "target_date": target_date,
            "trigger": trigger,
            "knowledge_trigger": knowledge_trigger or trigger,
        },
        name=f"briefing-task-{run_id}",
        daemon=True,
    )
    try:
        thread.start()
    except Exception as exc:
        with SessionLocal() as db:
            finish_run(
                db,
                run_id,
                "FAILED",
                error_message=f"后台任务启动失败: {exc}",
                meta={
                    "mode": "async",
                    "trigger": trigger,
                    "target_date": target_date.isoformat(),
                    "progress": 100,
                },
            )
            db.commit()
        _release_generation_slot(target_date, run_id)
        raise
    return {
        "run_id": run_id,
        "status": "QUEUED",
        "progress": 8,
        "target_date": target_date.isoformat(),
        "trigger": trigger,
        "queued_at": queued_at,
        "reused": False,
        "message": "早报生成任务已提交，前端会自动轮询运行状态。",
    }
