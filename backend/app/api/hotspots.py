"""热点捕手 API。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.runner import CONNECTOR_REGISTRY, load_sources_config, run_daily_briefing
from app.core.config import settings
from app.core.security import get_current_principal, is_admin
from app.services.member_view_service import member_briefing, member_event
from app.db.models import HotspotEvent, HotspotRawItem
from app.db.session import SessionLocal, get_db
from app.pipeline.evidence import FAKE_SOURCE_CODES, is_http_url, split_items_by_evidence
from app.pipeline.relevance import event_matches_product_focus
from app.pipeline.analysis import classify_by_rules
from app.schemas import HotspotEventDTO
from app.services.briefing_task_service import enqueue_briefing_generation, get_briefing_task_status
from app.services.feedback_service import (
    FeedbackEventNotFoundError,
    delete_event_feedback,
    get_feedback_overview,
    get_feedback_summary_map,
    list_event_feedback,
    list_feedback_records,
    upsert_event_feedback,
)
from app.services.push_config_service import PushConfigPayload, load_push_config, save_push_config
from app.services.push_service import push_briefing, test_onebot_connection
from app.services.scheduler_service import (
    SchedulerConfigPayload,
    SchedulerRunPayload,
    configure_scheduler,
    get_scheduler_status,
    load_scheduler_config,
    maybe_enqueue_briefing_knowledge_ingest,
    run_briefing_with_guard,
    save_scheduler_config,
)
from app.services.source_health_service import get_source_health_report
from app.services.system_log_service import write_system_log
from app.storage.repository import get_briefing_by_date, get_today_briefing, list_briefing_summaries, list_events, list_runs

router = APIRouter(prefix="/hotspots", tags=["hotspots"])


class PlatformHotspotFetchPayload(BaseModel):
    """前端按需抓取平台热点的请求体。"""

    sources: list[str] = Field(default_factory=lambda: ["github", "huggingface", "devto"])
    limit: int = Field(default=20, ge=1, le=50)
    timeout: int = Field(default=40, ge=5, le=90)


class EventFeedbackPayload(BaseModel):
    """热点情报人工反馈。"""

    action: str = Field(..., description="USEFUL / IRRELEVANT / FAVORITE / BLOCK")
    note: str | None = Field(default=None, max_length=1000)


class BriefingGenerateAsyncPayload(BaseModel):
    """早报异步生成参数。"""

    target_date: date | None = None
    trigger: str = Field(default="manual", max_length=40)


def _empty_platform_error(code: str) -> str:
    """按平台返回更可解释的空结果原因。"""
    return "未抓取到系统关注方向的公开数据；已过滤泛娱乐/生活内容，未使用样例兜底。"


def _normalize_jsonish(value: Any) -> Any:
    """把历史字符串字段规范成前端稳定可消费的 JSON 结构。"""
    if value is None:
        return []
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        # 兼容早期把 JSON list 错存成普通字符串的历史数据。
        return [part for part in stripped.replace(",", " ").replace("，", " ").replace(";", " ").replace("；", " ").split() if part]
    return value


def _category_is_corrupted(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    markers = ("?", "Ã", "Â", "â€", "ä", "å", "æ", "ç", "è", "é", "ï¼", "ã", "�")
    return any(marker in text for marker in markers)


def _repair_category(category: Any, source_codes: Any, title: Any) -> str:
    if not _category_is_corrupted(category):
        return str(category)
    sources = set(_normalize_jsonish(source_codes) or [])
    title_text = str(title or "").lower()
    topic = classify_by_rules(title_text)
    if topic != "综合":
        return topic
    if "arxiv_ai" in sources or any(key in title_text for key in ("llm", "transformer", "agent", "ai", "大模型", "人工智能")):
        return "AI / 大模型"
    if "github" in sources:
        return "开源技术"
    if "huggingface" in sources:
        return "AI / 大模型"
    if sources & {"hackernews", "devto"}:
        return "计算机技术"
    return "综合"


def _source_credibility_meta(source_codes: list[str]) -> tuple[float, str, str]:
    strong = {"github", "hackernews", "arxiv_ai", "huggingface", "devto"}
    general = set()
    sources = set(source_codes or [])
    score = 35 + min(len(sources), 4) * 12 + len(sources & strong) * 10 + len(sources & general) * 4
    score = max(0.0, min(100.0, round(score, 1)))
    level = "HIGH" if score >= 75 else "MEDIUM" if score >= 55 else "LOW"
    reason_parts = []
    if sources:
        reason_parts.append(f"{len(sources)} 个来源")
    if sources & strong:
        reason_parts.append("含强技术源")
    if sources & general:
        reason_parts.append("含公开热榜源")
    return score, level, "；".join(reason_parts) or "来源不足"


def orm_to_dict(obj):
    """把 ORM 对象转成响应字典。

    重点处理历史版本中可能写成字符串的 JSON 字段，避免前端渲染时报类型错误。
    """
    data = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    for key in ["source_codes", "main_opinions", "opposing_opinions", "content_suggestions", "rag_references", "historical_insights", "raw_item_ids"]:
        if key in data:
            data[key] = _normalize_jsonish(data[key])
    if "category" in data:
        data["category"] = _repair_category(data.get("category"), data.get("source_codes"), data.get("title"))
    if "credibility_score" in data and not data.get("credibility_score"):
        score, level, reason = _source_credibility_meta(data.get("source_codes") or [])
        data["credibility_score"] = score
        data["credibility_level"] = data.get("credibility_level") or level
        data["credibility_reason"] = data.get("credibility_reason") or reason
    if "is_fallback_sample" in data:
        data["is_fallback_sample"] = bool(data.get("is_fallback_sample"))
    if "raw_json" in data and isinstance(data.get("raw_json"), dict):
        raw_json = dict(data["raw_json"])
        if isinstance(raw_json.get("events"), list):
            raw_json["events"] = [
                sanitized
                for event in raw_json["events"]
                if _event_payload_has_real_evidence(event)
                for sanitized in [_sanitize_event_payload(event)]
                if sanitized and _event_payload_matches_product_focus(sanitized)
            ]
        data["raw_json"] = raw_json
    return data


def _sanitize_event_payload(event: dict[str, Any]) -> dict[str, Any]:
    """早报历史 JSON 返回前只保留可验证原文证据。"""
    sanitized = dict(event)
    items = []
    for item in sanitized.get("items") or []:
        if not isinstance(item, dict):
            continue
        payload = item.get("raw_payload") if isinstance(item.get("raw_payload"), dict) else {}
        source = str(item.get("source") or "").strip().lower()
        if source in FAKE_SOURCE_CODES or payload.get("is_fallback_sample") or not is_http_url(item.get("url")):
            continue
        clean_item = dict(item)
        clean_payload = dict(payload)
        clean_payload["has_real_evidence"] = True
        clean_payload["evidence_url"] = item.get("url")
        clean_payload["real_source"] = True
        clean_item["raw_payload"] = clean_payload
        items.append(clean_item)
    sanitized["items"] = items
    sanitized["has_real_evidence"] = bool(items)
    return sanitized


def _event_payload_has_real_evidence(event: Any) -> bool:
    if not isinstance(event, dict) or event.get("is_fallback_sample"):
        return False
    for item in event.get("items") or []:
        if not isinstance(item, dict):
            continue
        payload = item.get("raw_payload") if isinstance(item.get("raw_payload"), dict) else {}
        source = str(item.get("source") or "").strip().lower()
        if source not in FAKE_SOURCE_CODES and not payload.get("is_fallback_sample") and is_http_url(item.get("url")):
            return True
    return False


def _event_payload_matches_product_focus(event: dict[str, Any]) -> bool:
    try:
        return event_matches_product_focus(HotspotEventDTO.model_validate(event))
    except Exception:
        return False


def _raw_item_has_real_evidence(row: HotspotRawItem) -> bool:
    payload = row.raw_payload if isinstance(row.raw_payload, dict) else {}
    source = str(row.source_code or "").strip().lower()
    return source not in FAKE_SOURCE_CODES and not payload.get("is_fallback_sample") and is_http_url(row.url)


def _raw_item_to_dict(row: HotspotRawItem) -> dict[str, Any]:
    return {
        "id": row.id,
        "source": row.source_code,
        "source_name": row.source_name,
        "source_item_id": row.source_item_id,
        "title": row.title,
        "url": row.url,
        "rank": row.rank,
        "raw_hot_score": row.raw_hot_score,
        "content": row.content,
        "tags": _normalize_jsonish(row.tags),
        "captured_at": row.captured_at.isoformat() if row.captured_at else None,
        "raw_payload": row.raw_payload if isinstance(row.raw_payload, dict) else {},
    }


def event_to_dict(db: Session, row: HotspotEvent) -> dict[str, Any]:
    data = orm_to_dict(row)
    raw_ids: list[int] = []
    for value in _normalize_jsonish(data.get("raw_item_ids")):
        try:
            raw_ids.append(int(value))
        except (TypeError, ValueError):
            continue
    if not raw_ids:
        data["items"] = []
        data["has_real_evidence"] = False
        return data

    raw_rows = list(db.execute(select(HotspotRawItem).where(HotspotRawItem.id.in_(raw_ids[:20]))).scalars())
    raw_by_id = {item.id: item for item in raw_rows}
    ordered_rows = [raw_by_id[item_id] for item_id in raw_ids if item_id in raw_by_id]
    evidence_rows = [item for item in ordered_rows if _raw_item_has_real_evidence(item)]
    data["items"] = [_raw_item_to_dict(item) for item in evidence_rows[:8]]
    data["has_real_evidence"] = bool(evidence_rows)
    return data


def _attach_feedback(db: Session, event_payloads: list[dict[str, Any]], *, created_by: str) -> list[dict[str, Any]]:
    """给事件响应补充人工反馈摘要，并默认隐藏已屏蔽事件。"""
    summary_map = get_feedback_summary_map(db, [str(item.get("event_key") or "") for item in event_payloads], created_by=created_by)
    result: list[dict[str, Any]] = []
    for item in event_payloads:
        feedback = summary_map.get(str(item.get("event_key") or ""), {})
        item["feedback"] = feedback
        item["score_adjustment"] = int(feedback.get("score_adjustment") or 0)
        if feedback.get("is_blocked"):
            continue
        if item["score_adjustment"]:
            item["display_heat_score"] = round(max(0.0, min(100.0, float(item.get("heat_score") or 0) + item["score_adjustment"])), 2)
        else:
            item["display_heat_score"] = item.get("heat_score")
        result.append(item)
    return sorted(
        result,
        key=lambda row: (bool(row.get("feedback", {}).get("is_favorite")), float(row.get("display_heat_score") or row.get("heat_score") or 0)),
        reverse=True,
    )


def _attach_feedback_to_briefing_payload(db: Session, data: dict[str, Any] | None, *, created_by: str) -> dict[str, Any] | None:
    if not data or not isinstance(data.get("raw_json"), dict):
        return data
    raw_json = dict(data["raw_json"])
    events = raw_json.get("events")
    if isinstance(events, list):
        raw_json["events"] = _attach_feedback(db, [dict(event) for event in events if isinstance(event, dict)], created_by=created_by)
    data["raw_json"] = raw_json
    return data


def _briefing_response_with_optional_knowledge_ingest(
    db: Session,
    *,
    result,
    target_date: date,
    trigger: str,
) -> dict:
    """给手动生成/历史重生成补上"生成后自动入知识库"的可配置动作。

    任务中心和定时器已经在 `run_briefing_with_guard()` 里做了这个动作；
    这里单独处理直接点击"立即生成早报"的 API，避免用户每次生成后还要手动点一次入库。

    设计原则：
    - 早报生成成功才尝试入队。
    - 入库是异步任务，失败不影响早报生成结果。
    - 是否启用、哪些 trigger 生效，全部走 `config/sources.example.yml` 的 knowledge 配置。
    """
    data = result.model_dump(mode="json")
    if data.get("status") != "SUCCESS":
        return data

    knowledge_ingest = maybe_enqueue_briefing_knowledge_ingest(
        db,
        run_id=data.get("run_id"),
        target_date=target_date,
        trigger=trigger,
    )
    if knowledge_ingest:
        data["knowledge_ingest"] = knowledge_ingest
    return data


def _run_result_to_task_response(data: dict[str, Any], *, target_date: date, trigger: str) -> dict[str, Any]:
    run_id = data.get("run_id") or ""
    return {
        "ok": data.get("status") == "SUCCESS",
        "data": {
            "run_id": run_id,
            "status": data.get("status") or "UNKNOWN",
            "progress": 100,
            "target_date": target_date.isoformat(),
            "trigger": trigger,
            "message": data.get("message") or "",
            "total_events": data.get("total_events") or len(((data.get("briefing") or {}).get("events") or [])),
            "knowledge_ingest": data.get("knowledge_ingest"),
            "meta": {
                "mode": "sync-compat",
                "api_result": {
                    "status": data.get("status"),
                    "message": data.get("message"),
                    "total_events": data.get("total_events") or len(((data.get("briefing") or {}).get("events") or [])),
                },
                "knowledge_ingest": data.get("knowledge_ingest"),
            },
        },
    }


@router.post("/platform-hotspots/fetch")
def fetch_platform_hotspots(payload: PlatformHotspotFetchPayload | None = None) -> dict[str, Any]:
    """按需抓取官方 API 的系统关注热点。

    这个接口不写入 raw_item/event，也不污染每日早报主链路；
    主要用于前端手动验证某个平台现在能不能抓到真实公开数据。
    当前 connector 会按项目定位过滤：计算机行业、AI 产品、开源技术与产业财经。
    """
    payload = payload or PlatformHotspotFetchPayload()
    # Manual collection uses the same official API sources as the graduation profile.
    allowed_sources = {"github", "huggingface", "devto", "hackernews", "arxiv_ai"}
    normalized_sources: list[str] = []
    for source in payload.sources:
        code = str(source).strip().lower()
        if code not in allowed_sources:
            raise HTTPException(status_code=400, detail="Unsupported source")
        if code in allowed_sources and code not in normalized_sources:
            normalized_sources.append(code)
    if not normalized_sources:
        raise HTTPException(status_code=400, detail="Select an official API source")

    results: dict[str, Any] = {}
    total = 0
    for code in normalized_sources:
        connector_cls = CONNECTOR_REGISTRY.get(code)
        if not connector_cls:
            results[code] = {
                "code": code,
                "name": code,
                "status": "FAILED",
                "count": 0,
                "items": [],
                "error": "未知平台",
            }
            continue
        connector = connector_cls(max_items=payload.limit, timeout=payload.timeout)
        try:
            items = connector.fetch()
            accepted_items, dropped_fallback_count, dropped_no_evidence_count = split_items_by_evidence(items)
            rows = [item.model_dump(mode="json") for item in accepted_items[: payload.limit]]
            total += len(rows)
            results[code] = {
                "code": code,
                "name": connector.source_name,
                "status": "SUCCESS" if rows else "FAILED",
                "count": len(rows),
                "fetched_count": len(items),
                "dropped_fallback_count": dropped_fallback_count,
                "dropped_no_evidence_count": dropped_no_evidence_count,
                "items": rows,
                "error": "" if rows else _empty_platform_error(code),
            }
        except Exception as exc:  # noqa: BLE001
            results[code] = {
                "code": code,
                "name": getattr(connector, "source_name", code),
                "status": "FAILED",
                "count": 0,
                "items": [],
                "error": str(exc),
            }

    return {
        "ok": total > 0,
        "data": {
            "sources": results,
            "total": total,
            "limit": payload.limit,
            "timeout": payload.timeout,
        },
    }


@router.post("/briefings/generate", deprecated=True)
def generate_briefing(db: Session = Depends(get_db)):
    """[已弃用] 手动触发今日早报生成（同步阻塞）。

    P0-6: 该接口在请求线程内完整执行采集+分析+推送，可能耗时数分钟并耗尽 worker。
    生产环境请使用 `POST /api/hotspots/briefings/generate-async` 异步生成。
    本接口保留仅为向后兼容，后续版本将移除。
    """
    write_system_log(
        db,
        level="WARNING",
        module="manual",
        message="使用了已弃用的同步生成接口，建议迁移到 generate-async",
    )
    today = date.today()
    res = run_daily_briefing(db, target_date=today, trigger="manual")
    return _briefing_response_with_optional_knowledge_ingest(db, result=res, target_date=today, trigger="manual")


@router.post("/briefings/generate-async")
def generate_briefing_async(payload: BriefingGenerateAsyncPayload | None = None) -> dict[str, Any]:
    """异步触发早报生成，立即返回 run_id，前端轮询 `/runs/{run_id}`。"""
    payload = payload or BriefingGenerateAsyncPayload()
    target_date = payload.target_date or date.today()
    trigger = payload.trigger or "manual"
    try:
        task = enqueue_briefing_generation(
            target_date=target_date,
            trigger=trigger,
            knowledge_trigger=trigger,
        )
        return {"ok": True, "data": task}
    except RuntimeError as exc:
        if "cannot start new thread" not in str(exc).lower():
            raise
        # 兼容极端运行环境：线程创建失败时退化为同步执行，但响应仍保持 task 结构。
        with SessionLocal() as db:
            result = run_daily_briefing(db, target_date=target_date, trigger=trigger)
            data = _briefing_response_with_optional_knowledge_ingest(db, result=result, target_date=target_date, trigger=trigger)
            return _run_result_to_task_response(data, target_date=target_date, trigger=trigger)


@router.post("/briefings/today/push")
def push_today_briefing(db: Session = Depends(get_db)):
    """手动把今日早报推送到 QQ 机器人。"""
    write_system_log(db, level="INFO", module="push", message="手动触发今日早报推送")
    briefing = get_today_briefing(db)
    if not briefing:
        return {"ok": False, "message": "今天还没有早报，请先生成。"}
    config = load_sources_config()
    result = push_briefing(db, briefing=briefing, run_id="manual-push", push_cfg=config.get("push", {}))
    db.commit()
    return {"ok": result.get("status") == "SUCCESS", "message": result.get("message"), "data": result}


@router.get("/scheduler/config")
def get_scheduler_config():
    """读取自动调度配置。"""
    return {"data": load_scheduler_config(include_env=True)}


@router.put("/scheduler/config")
def update_scheduler_config(payload: SchedulerConfigPayload, request: Request):
    """保存自动调度配置，并立即刷新 APScheduler Job。"""
    data = save_scheduler_config(payload)
    scheduler = getattr(request.app.state, "scheduler", None)
    status = configure_scheduler(scheduler) if scheduler else {}
    return {"data": data, "status": status}


@router.get("/scheduler/status")
def scheduler_status(request: Request, db: Session = Depends(get_db)):
    """任务中心状态：是否启用、下次执行时间、今日是否已有早报、是否有 RUNNING 任务。"""
    scheduler = getattr(request.app.state, "scheduler", None)
    return {"data": get_scheduler_status(scheduler, db)}


@router.post("/scheduler/run")
def run_scheduler_now(payload: SchedulerRunPayload | None = None, db: Session = Depends(get_db)):
    """按调度策略手动执行一次。

    和"立即生成早报"不同：这里会走任务锁与同日防重复策略；
    force=true 时才会忽略"今天已有成功早报"的限制。
    """
    payload = payload or SchedulerRunPayload()
    write_system_log(
        db,
        level="INFO",
        module="scheduler",
        message=f"手动触发调度任务，force={payload.force}",
        extra=payload.model_dump(mode="json"),
    )
    return run_briefing_with_guard(
        db,
        trigger="task-center",
        target_date=payload.target_date,
        force=payload.force,
    )


@router.get("/push/config")
def get_push_config():
    """读取 QQ 机器人推送配置，token 只返回脱敏值。"""
    return {"data": load_push_config(include_env=True, mask_token=True)}


@router.put("/push/config")
def update_push_config(payload: PushConfigPayload):
    """保存 QQ 机器人推送配置到 config/push.local.json。"""
    return {"data": save_push_config(payload)}


@router.post("/push/config/test")
def test_push_config(payload: PushConfigPayload | None = None):
    """测试 OneBot HTTP API 连通性，不发送 QQ 消息。"""
    saved = load_push_config(include_env=True, mask_token=False)
    if payload:
        submitted = payload.model_dump(mode="json")
        if not submitted.get("access_token"):
            submitted["access_token"] = saved.get("access_token")
        cfg = {**saved, **submitted}
    else:
        cfg = saved
    return test_onebot_connection(cfg)


@router.get("/briefings/today")
def today_briefing(request: Request, db: Session = Depends(get_db)):
    """查询今日早报。若今天还没生成，前端会引导用户点击生成。"""
    briefing = get_today_briefing(db)
    principal = get_current_principal(request)
    data = orm_to_dict(briefing) if briefing else None
    if data and not is_admin(principal):
        data = member_briefing(data)
    return {"data": _attach_feedback_to_briefing_payload(db, data, created_by=principal["username"])}


@router.get("/briefings")
def briefings(request: Request, limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    # 列表页只返回轻量摘要字段；完整 markdown/raw_json 走详情接口按需加载。
    rows = list_briefing_summaries(db, limit=limit)
    if not is_admin(get_current_principal(request)):
        for row in rows:
            row["title"] = f"技术情报简报 {row['briefing_date']}"
            row["summary"] = ""
    return {"data": rows}


@router.get("/briefings/{briefing_date}")
def briefing_by_date(briefing_date: date, request: Request, db: Session = Depends(get_db)):
    """按日期查询历史早报。"""
    briefing = get_briefing_by_date(db, briefing_date)
    principal = get_current_principal(request)
    data = orm_to_dict(briefing) if briefing else None
    if data and not is_admin(principal):
        data = member_briefing(data)
    return {"data": _attach_feedback_to_briefing_payload(db, data, created_by=principal["username"])}


@router.post("/briefings/{briefing_date}/regenerate", deprecated=True)
def regenerate_briefing_by_date(briefing_date: date, db: Session = Depends(get_db)):
    """[已弃用] 重新生成指定日期早报（同步阻塞）。

    P0-6: 同步接口可能耗时数分钟。请使用
    `POST /api/hotspots/briefings/{briefing_date}/regenerate-async` 异步重生成。
    """
    write_system_log(
        db,
        level="WARNING",
        module="manual",
        message=f"使用了已弃用的同步重生成接口：{briefing_date.isoformat()}，建议迁移到 regenerate-async",
        extra={"briefing_date": briefing_date.isoformat()},
    )
    res = run_daily_briefing(db, target_date=briefing_date, trigger="history-regenerate")
    return _briefing_response_with_optional_knowledge_ingest(
        db,
        result=res,
        target_date=briefing_date,
        trigger="history-regenerate",
    )


@router.post("/briefings/{briefing_date}/regenerate-async")
def regenerate_briefing_by_date_async(briefing_date: date) -> dict[str, Any]:
    """异步重生成指定日期早报。"""
    trigger = "history-regenerate"
    try:
        task = enqueue_briefing_generation(
            target_date=briefing_date,
            trigger=trigger,
            knowledge_trigger=trigger,
        )
        return {"ok": True, "data": task}
    except RuntimeError as exc:
        if "cannot start new thread" not in str(exc).lower():
            raise
        db = SessionLocal()
        try:
            result = run_daily_briefing(db, target_date=briefing_date, trigger=trigger)
            data = _briefing_response_with_optional_knowledge_ingest(db, result=result, target_date=briefing_date, trigger=trigger)
            return _run_result_to_task_response(data, target_date=briefing_date, trigger=trigger)
        finally:
            db.close()


@router.get("/sources/health")
def source_health(
    limit: int = Query(30, ge=1, le=100),
    live: bool = Query(False, description="是否立即执行 connector.fetch() 做实时探测"),
    probe_limit: int = Query(10, ge=1, le=30, description="实时探测每个源最多抓取多少条"),
    timeout: int = Query(12, ge=3, le=60, description="实时探测单源超时时间，单位秒"),
    db: Session = Depends(get_db),
):
    """数据源健康详情。

    - 默认：读取历史 AgentRun 记录，展示长期成功率。
    - live=true：额外实时执行各 connector 的公开采集，用于证明"现在能抓到真实数据"。
    """
    return {"data": get_source_health_report(db, limit=limit, live=live, probe_limit=probe_limit, timeout=timeout)}


@router.get("/events")
def events(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    category: str | None = None,
    risk_level: str | None = None,
    db: Session = Depends(get_db),
):
    username = get_current_principal(request)["username"]
    rows = list_events(db, limit=limit, category=category, risk_level=risk_level, created_by=username)
    payloads = [event_to_dict(db, row) for row in rows]
    if not is_admin(get_current_principal(request)):
        payloads = [view for item in payloads for view in [member_event(item)] if view is not None]
    return {"data": _attach_feedback(db, payloads, created_by=username)}


@router.get("/feedback")
def feedback_records(
    request: Request,
    action: str | None = Query(None, description="USEFUL / IRRELEVANT / FAVORITE / BLOCK"),
    keyword: str | None = Query(None, description="按 event_key、标题或备注搜索"),
    category: str | None = Query(None, max_length=50, description="按情报分类精确筛选"),
    risk_level: str | None = Query(None, max_length=20, description="LOW / MEDIUM / HIGH"),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """查看全部人工反馈记录。

    前端"有用 / 无关 / 收藏 / 屏蔽"不会丢失：记录落到 hotspot_event_feedback 表，
    这里提供可回看、可筛选的管理入口。
    """
    try:
        items = list_feedback_records(
            db,
            action=action,
            keyword=keyword,
            category=category,
            risk_level=risk_level,
            limit=limit,
            created_by=get_current_principal(request)["username"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"data": {"items": items, "summary": get_feedback_overview(db, created_by=get_current_principal(request)["username"])}}


@router.get("/events/{event_key}/feedback")
def event_feedback(event_key: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """查看某条情报的人工反馈明细。"""
    return {"data": list_event_feedback(db, event_key=event_key, created_by=get_current_principal(request)["username"])}


@router.post("/events/{event_key}/feedback")
def create_event_feedback(event_key: str, payload: EventFeedbackPayload, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """给情报打反馈：有用、无关、收藏、屏蔽。

    产品意义：运营反馈会影响前端展示排序；屏蔽后该情报默认不再展示。
    """
    try:
        row = upsert_event_feedback(
            db,
            event_key=event_key,
            action=payload.action,
            note=payload.note,
            created_by=get_current_principal(request)["username"],
        )
    except FeedbackEventNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_system_log(
        db,
        level="INFO",
        module="feedback",
        message=f"热点情报反馈：{row.action}",
        extra={"event_key": event_key, "action": row.action, "note": row.note},
    )
    db.commit()
    return {
        "ok": True,
        "data": {
            "feedback": list_event_feedback(db, event_key=event_key, created_by=get_current_principal(request)["username"]),
            "summary": get_feedback_summary_map(db, [event_key], created_by=get_current_principal(request)["username"]).get(event_key, {}),
        },
    }


@router.delete("/events/{event_key}/feedback/{action}")
def remove_event_feedback(event_key: str, action: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """撤销某类人工反馈。"""
    try:
        deleted = delete_event_feedback(db, event_key=event_key, action=action, created_by=get_current_principal(request)["username"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_system_log(
        db,
        level="INFO",
        module="feedback",
        message=f"撤销热点情报反馈：{action.upper()}",
        extra={"event_key": event_key, "action": action.upper(), "deleted": deleted},
    )
    db.commit()
    return {
        "ok": True,
        "data": {
            "deleted_count": deleted,
            "feedback": list_event_feedback(db, event_key=event_key, created_by=get_current_principal(request)["username"]),
            "summary": get_feedback_summary_map(db, [event_key], created_by=get_current_principal(request)["username"]).get(event_key, {}),
        },
    }


@router.get("/runs")
def runs(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    rows = list_runs(db, limit=limit)
    return {"data": [orm_to_dict(row) for row in rows]}


@router.get("/runs/{run_id}")
def run_detail(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    task = get_briefing_task_status(db, run_id)
    if not task:
        raise HTTPException(status_code=404, detail="运行任务不存在")
    return {"data": task}
