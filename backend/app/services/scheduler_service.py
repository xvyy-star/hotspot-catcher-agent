"""自动调度任务中心服务。

这个服务把“每天早上自动跑”从 main.py 里拆出来，方便：
1. 前端页面读取/修改调度配置。
2. APScheduler 启动时统一装载任务。
3. 用 Redis 分布式锁防止多进程重复执行。
4. 用 AgentRun 记录 SKIPPED / FAILED / SUCCESS，便于生产可观测性。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import redis
from apscheduler.schedulers.background import BackgroundScheduler
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.runner import load_sources_config, run_daily_briefing
from app.core.config import PROJECT_ROOT, settings
from app.db.models import AgentRun, DailyBriefing
from app.db.session import SessionLocal
from app.services.knowledge_async_tasks import enqueue_briefing_ingest_thread
from app.storage.repository import create_run, finish_run

logger = logging.getLogger(__name__)

SCHEDULER_LOCAL_CONFIG_PATH = Path(PROJECT_ROOT / "config" / "scheduler.local.json")
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_JOB_ID = "daily_hotspot_briefing"
LOCK_KEY_PREFIX = "hotspot:briefing:lock"
LOCAL_LOCK = threading.Lock()
LOCAL_LOCK_TOKEN: str | None = None

DEFAULT_SCHEDULER_CONFIG: dict[str, Any] = {
    "enabled": settings.scheduler_enabled,
    "hour": settings.daily_hour,
    "minute": settings.daily_minute,
    "timezone": DEFAULT_TIMEZONE,
    "job_id": DEFAULT_JOB_ID,
    "allow_rerun_same_day": False,
    "lock_ttl_minutes": 90,
    "retry_times": 1,
    "retry_delay_seconds": 30,
    "misfire_grace_seconds": 3600,
    "coalesce": True,
    "max_instances": 1,
}


class SchedulerConfigPayload(BaseModel):
    """前端任务中心可编辑的调度配置。"""

    enabled: bool = True
    hour: int = Field(default=8, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    timezone: str = DEFAULT_TIMEZONE
    allow_rerun_same_day: bool = False
    lock_ttl_minutes: int = Field(default=90, ge=5, le=720)
    retry_times: int = Field(default=1, ge=0, le=5)
    retry_delay_seconds: int = Field(default=30, ge=1, le=600)
    misfire_grace_seconds: int = Field(default=3600, ge=60, le=86400)
    coalesce: bool = True
    max_instances: int = Field(default=1, ge=1, le=3)


class SchedulerRunPayload(BaseModel):
    """任务中心手动触发参数。"""

    force: bool = False
    target_date: date | None = None


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _load_local_scheduler_config() -> dict[str, Any]:
    if not SCHEDULER_LOCAL_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(SCHEDULER_LOCAL_CONFIG_PATH.read_text(encoding="utf-8")).get("scheduler") or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 scheduler.local.json 失败，使用默认调度配置: %s", exc)
        return {}


def _apply_env_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    """服务器部署时允许用 HOTSPOT_* 环境变量覆盖页面配置。

    注意：普通 `.env` 里的 SCHEDULER_ENABLED / DAILY_BRIEFING_HOUR 只作为默认值；
    真正强制覆盖页面保存值时，使用 HOTSPOT_SCHEDULER_*，避免本地演示环境的 .env 让页面保存失效。
    """
    result = dict(cfg)
    env_map = {
        "enabled": "HOTSPOT_SCHEDULER_ENABLED",
        "hour": "HOTSPOT_SCHEDULER_HOUR",
        "minute": "HOTSPOT_SCHEDULER_MINUTE",
        "timezone": "HOTSPOT_SCHEDULER_TIMEZONE",
        "allow_rerun_same_day": "HOTSPOT_SCHEDULER_ALLOW_RERUN_SAME_DAY",
        "lock_ttl_minutes": "HOTSPOT_SCHEDULER_LOCK_TTL_MINUTES",
        "retry_times": "HOTSPOT_SCHEDULER_RETRY_TIMES",
        "retry_delay_seconds": "HOTSPOT_SCHEDULER_RETRY_DELAY_SECONDS",
    }
    for key, env_key in env_map.items():
        raw = os.getenv(env_key)
        if raw is None or raw == "":
            continue
        if key in {"enabled", "allow_rerun_same_day"}:
            result[key] = _parse_bool(raw)
        elif key == "timezone":
            result[key] = raw
        else:
            result[key] = int(raw)
    return result


def load_scheduler_config(*, include_env: bool = False) -> dict[str, Any]:
    """读取调度配置：默认配置 + 本地 JSON + 可选环境变量覆盖。"""
    cfg = {**DEFAULT_SCHEDULER_CONFIG, **_load_local_scheduler_config()}
    if include_env:
        cfg = _apply_env_overrides(cfg)
    # 统一补齐/规整字段，避免旧配置缺字段导致前端报错。
    payload = SchedulerConfigPayload(**{k: v for k, v in cfg.items() if k in SchedulerConfigPayload.model_fields})
    result = {**DEFAULT_SCHEDULER_CONFIG, **payload.model_dump(mode="json")}
    result["job_id"] = str(cfg.get("job_id") or DEFAULT_JOB_ID)
    result["local_config_path"] = str(SCHEDULER_LOCAL_CONFIG_PATH)
    return result


def load_knowledge_auto_ingest_config() -> dict[str, Any]:
    """读取“早报自动写入知识库”配置。

    这个配置放在 sources 配置文件里，原因是它属于 Agent 输出后的业务动作，
    跟采集源、早报生成、推送一样，都应该随部署环境可配置。
    """
    default = {
        "auto_ingest_daily_briefing": False,
        "auto_ingest_triggers": ["scheduler"],
        "chunk_size": 800,
        "overlap": 120,
        "duplicate_policy": "skip_same_content_replace_changed",
    }
    try:
        raw = (load_sources_config().get("knowledge") or {})
        cfg = {**default, **raw}
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取知识库自动入库配置失败，使用默认关闭策略: %s", exc)
        cfg = default

    triggers = cfg.get("auto_ingest_triggers") or ["scheduler"]
    if isinstance(triggers, str):
        triggers = [triggers]
    enabled_value = cfg.get("auto_ingest_daily_briefing")
    enabled = _parse_bool(enabled_value) if isinstance(enabled_value, str) else bool(enabled_value)
    return {
        "auto_ingest_daily_briefing": enabled,
        "auto_ingest_triggers": [str(item) for item in triggers],
        "chunk_size": int(cfg.get("chunk_size") or 800),
        "overlap": int(cfg.get("overlap") or 120),
        "duplicate_policy": str(cfg.get("duplicate_policy") or "skip_same_content_replace_changed"),
    }


def save_scheduler_config(payload: SchedulerConfigPayload) -> dict[str, Any]:
    """保存任务中心配置到 config/scheduler.local.json。"""
    data = payload.model_dump(mode="json")
    data["job_id"] = DEFAULT_JOB_ID
    SCHEDULER_LOCAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULER_LOCAL_CONFIG_PATH.write_text(
        json.dumps({"scheduler": data}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return load_scheduler_config(include_env=True)


@dataclass
class TaskLock:
    acquired: bool
    key: str
    token: str
    backend: str
    message: str = ""


def _redis_client():
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def briefing_lock_key(target_date: date) -> str:
    """Return the shared per-day lock key used by every briefing entry point."""
    return f"{LOCK_KEY_PREFIX}:{target_date.isoformat()}"


def acquire_task_lock(target_date: date, ttl_minutes: int) -> TaskLock:
    """获取任务锁。

    优先用 Redis `SET key value NX EX ttl`，这是多进程/多服务器可用的分布式锁。
    默认在 Redis 异常时停止本次任务，避免多实例各自退化到本地锁后重复执行。
    """
    key = briefing_lock_key(target_date)
    token = uuid.uuid4().hex
    ttl_seconds = max(60, int(ttl_minutes) * 60)
    try:
        ok = _redis_client().set(key, token, nx=True, ex=ttl_seconds)
        if ok:
            return TaskLock(True, key, token, "redis")
        return TaskLock(False, key, token, "redis", "已有早报任务正在执行，已跳过本次触发")
    except Exception as exc:  # noqa: BLE001
        if not bool(getattr(settings, "scheduler_lock_fail_open", False)):
            logger.error("Redis 任务锁不可用，本次任务已停止以防止重复执行: %s", exc)
            return TaskLock(False, key, token, "redis-error", f"Redis 任务锁不可用，已停止本次触发：{exc}")

        logger.warning("Redis 锁不可用，按配置退化为进程内锁: %s", exc)
        global LOCAL_LOCK_TOKEN
        if LOCAL_LOCK.acquire(blocking=False):
            LOCAL_LOCK_TOKEN = token
            return TaskLock(True, key, token, "process", f"Redis 不可用，使用本进程锁：{exc}")
        return TaskLock(False, key, token, "process", "本进程已有早报任务正在执行，已跳过本次触发")


def release_task_lock(lock: TaskLock) -> None:
    if not lock.acquired:
        return
    if lock.backend == "redis":
        try:
            client = _redis_client()
            # 只有 token 匹配才删除，避免误删别人后来拿到的新锁。
            script = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            else
                return 0
            end
            """
            client.eval(script, 1, lock.key, lock.token)
        except Exception as exc:  # noqa: BLE001
            logger.warning("释放 Redis 任务锁失败: %s", exc)
        return

    global LOCAL_LOCK_TOKEN
    if lock.backend == "process" and LOCAL_LOCK_TOKEN == lock.token:
        LOCAL_LOCK_TOKEN = None
        LOCAL_LOCK.release()


def _create_skipped_run(db: Session, *, trigger: str, reason: str, target_date: date, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """把跳过也写入 AgentRun，前端任务中心才能看到完整轨迹。"""
    run_id = f"{trigger}-skip-{target_date.isoformat()}-{uuid.uuid4().hex[:8]}"
    create_run(db, run_id)
    finish_run(
        db,
        run_id,
        "SKIPPED",
        total_raw=0,
        total_events=0,
        error_message=None,
        meta={"trigger": trigger, "target_date": target_date.isoformat(), "reason": reason, **(meta or {})},
    )
    db.commit()
    return {"run_id": run_id, "status": "SKIPPED", "message": reason}


def _existing_success_briefing(db: Session, target_date: date) -> DailyBriefing | None:
    return db.execute(
        select(DailyBriefing).where(
            DailyBriefing.briefing_date == target_date,
            DailyBriefing.status.in_({"SUCCESS", "LOW_REAL_COVERAGE"}),
        )
    ).scalar_one_or_none()


def _append_agent_run_meta(db: Session, run_id: str | None, patch: dict[str, Any]) -> None:
    """追加更新 AgentRun.meta。

    JSON 字段要整体重新赋值，SQLAlchemy 才能稳定感知变更。
    """
    if not run_id:
        return
    row = db.execute(select(AgentRun).where(AgentRun.run_id == run_id)).scalar_one_or_none()
    if not row:
        return
    row.meta = {**(row.meta or {}), **patch}
    db.commit()


def maybe_enqueue_briefing_knowledge_ingest(
    db: Session,
    *,
    run_id: str | None,
    target_date: date,
    trigger: str,
) -> dict[str, Any] | None:
    """按配置把生成好的早报异步写入知识库。

    设计要点：
    - 只负责“入队”，不阻塞早报任务成功返回。
    - 入队失败只写入 AgentRun.meta，不把早报任务改成失败。
    - 真正导入状态由 KnowledgeIngestRun 单独追踪。
    """
    cfg = load_knowledge_auto_ingest_config()
    if not bool(cfg.get("auto_ingest_daily_briefing")):
        return None

    allowed_triggers = {str(item) for item in cfg.get("auto_ingest_triggers") or []}
    if allowed_triggers and trigger not in allowed_triggers:
        return None

    try:
        run = enqueue_briefing_ingest_thread(
            briefing_date=target_date,
            chunk_size=int(cfg.get("chunk_size") or 800),
            overlap=int(cfg.get("overlap") or 120),
        )
        result = {
            "enabled": True,
            "queued": True,
            "mode": "thread",
            "briefing_date": target_date.isoformat(),
            "run_id": run.get("id"),
            "status": run.get("status"),
            "duplicate_policy": cfg.get("duplicate_policy"),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("早报自动入库任务入队失败 run_id=%s date=%s", run_id, target_date)
        result = {
            "enabled": True,
            "queued": False,
            "briefing_date": target_date.isoformat(),
            "status": "FAILED_TO_QUEUE",
            "error_message": str(exc),
        }

    _append_agent_run_meta(db, run_id, {"knowledge_ingest": result})
    return result


def run_briefing_with_guard(
    db: Session,
    *,
    trigger: str = "scheduler",
    target_date: date | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """带任务锁和同日防重复的早报执行入口。"""
    cfg = load_scheduler_config(include_env=True)
    day = target_date or datetime.now(ZoneInfo(str(cfg.get("timezone") or DEFAULT_TIMEZONE))).date()
    lock = acquire_task_lock(day, int(cfg.get("lock_ttl_minutes") or 90))
    if not lock.acquired:
        return _create_skipped_run(db, trigger=trigger, reason=lock.message, target_date=day, meta={"lock_key": lock.key, "lock_backend": lock.backend})

    try:
        if not force and not bool(cfg.get("allow_rerun_same_day")):
            existing = _existing_success_briefing(db, day)
            if existing:
                return _create_skipped_run(
                    db,
                    trigger=trigger,
                    reason="今天已经有成功早报，防重复策略已跳过本次执行",
                    target_date=day,
                    meta={"briefing_id": existing.id, "lock_backend": lock.backend},
                )

        result = run_daily_briefing(db, target_date=day, trigger=trigger)
        data = result.model_dump(mode="json")
        data["lock_backend"] = lock.backend
        data["lock_message"] = lock.message
        if data.get("status") == "SUCCESS":
            knowledge_ingest = maybe_enqueue_briefing_knowledge_ingest(
                db,
                run_id=data.get("run_id"),
                target_date=day,
                trigger=trigger,
            )
            if knowledge_ingest:
                data["knowledge_ingest"] = knowledge_ingest
        return data
    finally:
        release_task_lock(lock)


def run_scheduled_job() -> dict[str, Any]:
    """APScheduler 实际调用的函数，带失败重试。"""
    cfg = load_scheduler_config(include_env=True)
    if not bool(cfg.get("enabled")):
        logger.info("调度器配置为 disabled，本次触发忽略")
        return {"status": "SKIPPED", "message": "scheduler disabled"}

    retry_times = int(cfg.get("retry_times") or 0)
    retry_delay = int(cfg.get("retry_delay_seconds") or 30)
    last_result: dict[str, Any] = {}
    for attempt in range(retry_times + 1):
        db = SessionLocal()
        try:
            last_result = run_briefing_with_guard(db, trigger="scheduler", force=False)
        finally:
            db.close()

        if last_result.get("status") != "FAILED":
            break
        if attempt < retry_times:
            logger.warning("定时早报失败，%s 秒后第 %s 次重试：%s", retry_delay, attempt + 1, last_result.get("message"))
            time.sleep(retry_delay)
    return last_result


def configure_scheduler(scheduler: BackgroundScheduler) -> dict[str, Any]:
    """根据当前配置创建/更新 APScheduler Job。"""
    cfg = load_scheduler_config(include_env=True)
    job_id = str(cfg.get("job_id") or DEFAULT_JOB_ID)

    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    if bool(cfg.get("enabled")):
        scheduler.add_job(
            run_scheduled_job,
            "cron",
            hour=int(cfg.get("hour") or 8),
            minute=int(cfg.get("minute") or 0),
            timezone=str(cfg.get("timezone") or DEFAULT_TIMEZONE),
            id=job_id,
            replace_existing=True,
            max_instances=int(cfg.get("max_instances") or 1),
            coalesce=bool(cfg.get("coalesce")),
            misfire_grace_time=int(cfg.get("misfire_grace_seconds") or 3600),
        )
        if not scheduler.running:
            scheduler.start()
        logger.info("热点早报定时任务已配置：每天 %02d:%02d %s", int(cfg.get("hour") or 8), int(cfg.get("minute") or 0), cfg.get("timezone"))
    return get_scheduler_status(scheduler)


def get_scheduler_status(scheduler: BackgroundScheduler | None = None, db: Session | None = None) -> dict[str, Any]:
    """返回任务中心状态。"""
    cfg = load_scheduler_config(include_env=True)
    job = scheduler.get_job(str(cfg.get("job_id") or DEFAULT_JOB_ID)) if scheduler else None
    today = datetime.now(ZoneInfo(str(cfg.get("timezone") or DEFAULT_TIMEZONE))).date()
    today_briefing: DailyBriefing | None = None
    running_count = 0
    if db is not None:
        today_briefing = db.execute(select(DailyBriefing).where(DailyBriefing.briefing_date == today)).scalar_one_or_none()
        running_count = db.execute(select(AgentRun).where(AgentRun.status == "RUNNING")).scalars().all().__len__()

    return {
        "config": cfg,
        "knowledge_auto_ingest": load_knowledge_auto_ingest_config(),
        "scheduler_running": bool(scheduler.running) if scheduler else False,
        "job_exists": job is not None,
        "job_id": str(cfg.get("job_id") or DEFAULT_JOB_ID),
        "next_run_time": job.next_run_time.isoformat() if job and job.next_run_time else None,
        "today": today.isoformat(),
        "today_has_briefing": today_briefing is not None,
        "today_briefing_status": today_briefing.status if today_briefing else None,
        "today_briefing_updated_at": today_briefing.updated_at.isoformat() if today_briefing and today_briefing.updated_at else None,
        "running_count": running_count,
        "lock_key": briefing_lock_key(today),
        "local_config_path": str(SCHEDULER_LOCAL_CONFIG_PATH),
    }
