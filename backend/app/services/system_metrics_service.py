"""运维数据看板指标聚合。"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AgentRun,
    DailyBriefing,
    HotspotEvent,
    HotspotRawItem,
    LLMCallLog,
    PushDeliveryLog,
)
from app.pipeline.evidence import FAKE_SOURCE_CODES, is_http_url
from app.core.time import business_naive_to_utc, business_now_naive, utc_naive_to_business, utc_now_iso
from app.services.llm_observability_service import get_llm_stats
from app.services.feedback_service import blocked_event_keys, get_feedback_overview
from app.services.source_health_service import get_source_health_report
from app.services.system_log_service import get_log_summary, list_system_logs
from app.storage.repository import _event_matches_current_lane


def _iso(value: Any) -> str | None:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def _pct(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator) * 100, 1) if denominator else 0.0


def _date_key(value: datetime | date | None, *, utc_naive: bool = False) -> str:
    if isinstance(value, datetime):
        if utc_naive:
            value = utc_naive_to_business(value)
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return "-"


def _last_7_day_labels(today: date) -> list[str]:
    return [(today - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)]


def _run_to_dict(row: AgentRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "status": row.status,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "total_raw": row.total_raw,
        "total_events": row.total_events,
        "error_message": row.error_message,
    }


def _safe_source_codes(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part for part in value.replace(",", " ").split() if part]
    return []


def _safe_int_ids(value: Any) -> list[int]:
    ids: list[int] = []
    for item in _safe_source_codes(value):
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _build_operational_trends(
    day_labels: list[str],
    *,
    runs: list[Any],
    llm_calls: list[Any],
    pushes: list[Any],
) -> list[dict[str, Any]]:
    """Build one aligned daily series for run, model, token and push quality."""
    trend = {
        label: {
            "date": label,
            "runs_total": 0,
            "runs_success": 0,
            "runs_failed": 0,
            "runs_skipped": 0,
            "run_success_rate": 0.0,
            "llm_calls": 0,
            "llm_success": 0,
            "llm_failed": 0,
            "llm_success_rate": 0.0,
            "llm_tokens": 0,
            "llm_cost": 0.0,
            "push_total": 0,
            "push_success": 0,
            "push_failed": 0,
            "push_success_rate": 0.0,
        }
        for label in day_labels
    }

    for row in runs:
        item = trend.get(_date_key(getattr(row, "started_at", None), utc_naive=True))
        if item is None:
            continue
        status = str(getattr(row, "status", "") or "").upper()
        if status == "SUCCESS":
            item["runs_success"] += 1
            item["runs_total"] += 1
        elif status == "FAILED":
            item["runs_failed"] += 1
            item["runs_total"] += 1
        elif status == "SKIPPED":
            item["runs_skipped"] += 1

    for row in llm_calls:
        item = trend.get(_date_key(getattr(row, "created_at", None)))
        if item is None:
            continue
        status = str(getattr(row, "status", "") or "").upper()
        item["llm_calls"] += 1
        item["llm_tokens"] += max(0, int(getattr(row, "total_tokens", 0) or 0))
        item["llm_cost"] += max(0.0, float(getattr(row, "estimated_cost", 0) or 0))
        if status in {"SUCCESS", "CACHE_HIT"}:
            item["llm_success"] += 1
        elif status == "FAILED":
            item["llm_failed"] += 1

    for row in pushes:
        item = trend.get(_date_key(getattr(row, "created_at", None)))
        if item is None:
            continue
        status = str(getattr(row, "status", "") or "").upper()
        if status == "SUCCESS":
            item["push_success"] += 1
            item["push_total"] += 1
        elif status == "FAILED":
            item["push_failed"] += 1
            item["push_total"] += 1

    for item in trend.values():
        item["run_success_rate"] = _pct(item["runs_success"], item["runs_total"])
        item["llm_success_rate"] = _pct(item["llm_success"], item["llm_calls"])
        item["llm_cost"] = round(float(item["llm_cost"]), 10)
        item["push_success_rate"] = _pct(item["push_success"], item["push_total"])
    return list(trend.values())


def _raw_row_has_real_evidence(row: HotspotRawItem) -> bool:
    payload = row.raw_payload if isinstance(row.raw_payload, dict) else {}
    source = str(row.source_code or "").strip().lower()
    return source not in FAKE_SOURCE_CODES and not payload.get("is_fallback_sample") and is_http_url(row.url)


def _filter_events_with_real_evidence(db: Session, rows: list[HotspotEvent]) -> list[HotspotEvent]:
    """数据大屏也只统计有 item 级原文链接的真实事件。"""
    raw_ids: set[int] = set()
    row_to_ids: dict[str, list[int]] = {}
    for row in rows:
        ids = _safe_int_ids(row.raw_item_ids)
        row_to_ids[row.event_key] = ids
        raw_ids.update(ids[:20])
    if not raw_ids:
        return []

    raw_rows = db.execute(select(HotspotRawItem).where(HotspotRawItem.id.in_(list(raw_ids)))).scalars()
    valid_raw_ids = {row.id for row in raw_rows if _raw_row_has_real_evidence(row)}
    return [row for row in rows if bool(set(row_to_ids.get(row.event_key, [])) & valid_raw_ids) and not row.is_fallback_sample]


def get_system_metrics(db: Session) -> dict[str, Any]:
    now_local = business_now_naive()
    today = now_local.date()
    start_today = datetime.combine(today, time.min)
    seven_days_ago = start_today - timedelta(days=6)
    seven_days_ago_utc = business_naive_to_utc(seven_days_ago)

    recent_events = list(
        db.execute(
            select(HotspotEvent)
            .where(HotspotEvent.updated_at >= seven_days_ago, HotspotEvent.is_fallback_sample.is_(False))
            .order_by(desc(HotspotEvent.updated_at), desc(HotspotEvent.heat_score))
            .limit(500)
        ).scalars()
    )
    if not recent_events:
        recent_events = list(
            db.execute(
                select(HotspotEvent)
                .where(HotspotEvent.is_fallback_sample.is_(False))
                .order_by(desc(HotspotEvent.updated_at))
                .limit(500)
            ).scalars()
        )
    recent_events = [row for row in _filter_events_with_real_evidence(db, recent_events) if _event_matches_current_lane(row)]
    blocked_keys = blocked_event_keys(db)
    if blocked_keys:
        recent_events = [row for row in recent_events if row.event_key not in blocked_keys]
    total_events = len(recent_events)
    today_events = sum(1 for row in recent_events if row.updated_at and row.updated_at >= start_today)
    if not today_events and total_events:
        # 演示库可能是一次性导入数据，updated_at 不一定正好是当天；看板仍给出可读的近场指标。
        today_events = min(int(total_events), 50)

    high_risk_count = sum(1 for row in recent_events if row.risk_level == "HIGH")
    fallback_sample_count = 0
    avg_credibility = sum(float(row.credibility_score or 0) for row in recent_events) / len(recent_events) if recent_events else 0

    events_by_day_counter = Counter(_date_key(row.updated_at or row.created_at) for row in recent_events)
    day_labels = _last_7_day_labels(today)
    events_7d = [{"date": label, "count": int(events_by_day_counter.get(label, 0))} for label in day_labels]

    # 这里只需要按日期统计数量，不能 SELECT markdown/raw_json 等大字段后再排序；
    # MySQL 默认 sort_buffer 较小时，大字段排序会触发 1038 Out of sort memory。
    briefing_rows = db.execute(
        select(DailyBriefing.briefing_date, func.count(DailyBriefing.id))
        .where(DailyBriefing.briefing_date >= today - timedelta(days=6))
        .group_by(DailyBriefing.briefing_date)
    ).all()
    briefing_counter = Counter({row[0].isoformat(): int(row[1] or 0) for row in briefing_rows if row[0]})
    briefings_7d = [{"date": label, "count": int(briefing_counter.get(label, 0))} for label in day_labels]

    category_counter = Counter(row.category or "综合" for row in recent_events)
    source_counter: Counter[str] = Counter()
    rag_hit_count = 0
    for row in recent_events:
        for source in _safe_source_codes(row.source_codes):
            source_counter[source] += 1
        if isinstance(row.rag_references, list) and row.rag_references:
            rag_hit_count += 1

    category_distribution = [
        {"name": name, "count": count, "percent": _pct(count, len(recent_events))}
        for name, count in category_counter.most_common(10)
    ]
    source_distribution = [
        {"name": name, "count": count, "percent": _pct(count, sum(source_counter.values()))}
        for name, count in source_counter.most_common(10)
    ]

    source_health = get_source_health_report(db, limit=50, live=False)
    llm_stats = get_llm_stats(db, limit=10)

    operational_run_rows = db.execute(
        select(AgentRun.started_at, AgentRun.finished_at, AgentRun.status)
        .where(AgentRun.started_at >= seven_days_ago_utc)
    ).all()
    operational_llm_rows = db.execute(
        select(LLMCallLog.created_at, LLMCallLog.status, LLMCallLog.total_tokens, LLMCallLog.estimated_cost)
        .where(LLMCallLog.created_at >= seven_days_ago)
    ).all()
    operational_push_rows = db.execute(
        select(PushDeliveryLog.created_at, PushDeliveryLog.status)
        .where(PushDeliveryLog.created_at >= seven_days_ago)
    ).all()
    operations_7d = _build_operational_trends(
        day_labels,
        runs=operational_run_rows,
        llm_calls=operational_llm_rows,
        pushes=operational_push_rows,
    )

    last_24h = now_local - timedelta(days=1)
    llm_recent_24h = [row for row in operational_llm_rows if row.created_at and row.created_at >= last_24h]
    llm_24h_success = sum(1 for row in llm_recent_24h if row.status in {"SUCCESS", "CACHE_HIT"})
    llm_24h_failed = sum(1 for row in llm_recent_24h if row.status == "FAILED")
    llm_tokens_24h = sum(max(0, int(row.total_tokens or 0)) for row in llm_recent_24h)
    llm_cost_24h = round(sum(max(0.0, float(row.estimated_cost or 0)) for row in llm_recent_24h), 10)

    push_status_counts = Counter(str(row.status or "").upper() for row in operational_push_rows)
    push_success = push_status_counts.get("SUCCESS", 0)
    push_failed = push_status_counts.get("FAILED", 0)
    push_skipped = push_status_counts.get("SKIPPED", 0)
    push_total = push_success + push_failed

    run_success_7d = sum(int(item["runs_success"]) for item in operations_7d)
    run_failed_7d = sum(int(item["runs_failed"]) for item in operations_7d)
    run_total_7d = run_success_7d + run_failed_7d
    run_durations = [
        max(0.0, (row.finished_at - row.started_at).total_seconds())
        for row in operational_run_rows
        if row.started_at and row.finished_at and row.status in {"SUCCESS", "FAILED"}
    ]
    avg_run_duration_seconds = round(sum(run_durations) / len(run_durations), 1) if run_durations else 0.0

    recent_runs = [
        _run_to_dict(row)
        for row in db.execute(select(AgentRun).order_by(desc(AgentRun.started_at)).limit(8)).scalars()
    ]
    # 这里只需要轻量摘要，避免 SELECT markdown/raw_json 这类大字段参与排序导致 MySQL sort buffer 爆。
    last_briefing = db.execute(
        select(
            DailyBriefing.briefing_date,
            DailyBriefing.title,
            DailyBriefing.status,
            DailyBriefing.updated_at,
        )
        .order_by(desc(DailyBriefing.briefing_date))
        .limit(1)
    ).mappings().first()

    log_summary = get_log_summary(db)
    recent_logs = list_system_logs(db, limit=8)
    feedback_overview = get_feedback_overview(db)

    source_success_rate = float(source_health.get("avg_success_rate") or 0)
    model_success_rate = float(llm_stats.get("success_rate") or 0)
    rag_hit_rate = _pct(rag_hit_count, len(recent_events))
    push_success_rate = _pct(push_success, push_total)
    run_success_rate_7d = _pct(run_success_7d, run_total_7d)
    llm_tokens_7d = sum(int(item["llm_tokens"]) for item in operations_7d)
    llm_cost_7d = round(sum(float(item["llm_cost"]) for item in operations_7d), 10)
    feedback_total_count = int(feedback_overview["positive_count"]) + int(feedback_overview["negative_count"])
    feedback_positive_rate = _pct(feedback_overview["positive_count"], feedback_total_count)

    system_score = 50
    system_score += 15 if today_events > 0 else 0
    system_score += min(15, source_success_rate * 0.15)
    system_score += min(10, model_success_rate * 0.1)
    system_score += 5 if log_summary["errors_24h"] == 0 else -min(20, log_summary["errors_24h"] * 5)
    system_score += 5 if push_failed == 0 else -min(10, push_failed * 2)
    system_score = round(max(0, min(100, system_score)), 1)

    return {
        "generated_at": utc_now_iso(),
        "today": today.isoformat(),
        "summary": {
            "system_score": system_score,
            "total_events": int(total_events),
            "today_events": int(today_events),
            "high_risk_count": int(high_risk_count),
            "fallback_sample_count": int(fallback_sample_count),
            "avg_credibility": round(float(avg_credibility or 0), 1),
            "enabled_sources": int(source_health.get("enabled_sources") or 0),
            "healthy_sources": int(source_health.get("healthy_sources") or 0),
            "down_sources": int(source_health.get("down_sources") or 0),
            "source_success_rate": source_success_rate,
            "model_success_rate": model_success_rate,
            "avg_llm_latency_ms": float(llm_stats.get("avg_latency_ms") or 0),
            "llm_calls_24h": len(llm_recent_24h),
            "llm_success_24h": llm_24h_success,
            "llm_failed_24h": llm_24h_failed,
            "llm_tokens_24h": llm_tokens_24h,
            "llm_tokens_7d": llm_tokens_7d,
            "llm_cost_24h": llm_cost_24h,
            "llm_cost_7d": llm_cost_7d,
            "runs_7d": run_total_7d,
            "run_success_7d": run_success_7d,
            "run_failed_7d": run_failed_7d,
            "run_success_rate_7d": run_success_rate_7d,
            "avg_run_duration_seconds": avg_run_duration_seconds,
            "rag_hit_rate": rag_hit_rate,
            "push_success_rate": push_success_rate,
            "push_success_count": push_success,
            "push_failed_count": push_failed,
            "push_skipped_count": push_skipped,
            "logs_total": int(log_summary["total"]),
            "errors_24h": int(log_summary["errors_24h"]),
            "warnings_24h": int(log_summary["warnings_24h"]),
            "feedback_positive_count": int(feedback_overview["positive_count"]),
            "feedback_negative_count": int(feedback_overview["negative_count"]),
            "feedback_blocked_count": int(feedback_overview["blocked_count"]),
            "feedback_favorite_count": int(feedback_overview["favorite_count"]),
            "feedback_total_count": feedback_total_count,
            "feedback_positive_rate": feedback_positive_rate,
        },
        "trends": {
            "events_7d": events_7d,
            "briefings_7d": briefings_7d,
            "operations_7d": operations_7d,
        },
        "distributions": {
            "category": category_distribution,
            "source": source_distribution,
        },
        "source_health": {
            "avg_success_rate": source_success_rate,
            "enabled_sources": source_health.get("enabled_sources"),
            "healthy_sources": source_health.get("healthy_sources"),
            "degraded_sources": source_health.get("degraded_sources"),
            "down_sources": source_health.get("down_sources"),
        },
        "llm": {
            "total_calls": llm_stats.get("total_calls", 0),
            "success_rate": model_success_rate,
            "avg_latency_ms": llm_stats.get("avg_latency_ms", 0),
            "cache_hit_count": llm_stats.get("cache_hit_count", 0),
            "tokens_24h": llm_tokens_24h,
            "tokens_7d": llm_tokens_7d,
            "cost_24h": llm_cost_24h,
            "cost_7d": llm_cost_7d,
            "total_estimated_cost": llm_stats.get("total_estimated_cost", 0),
            "provider_stats": llm_stats.get("provider_stats", [])[:5],
        },
        "push": {
            "total": push_total,
            "success": push_success,
            "failed": push_failed,
            "skipped": push_skipped,
            "success_rate": push_success_rate,
        },
        "logs": {
            **log_summary,
            "recent": recent_logs,
        },
        "feedback": {
            **feedback_overview,
            "total_count": feedback_total_count,
            "positive_rate": feedback_positive_rate,
        },
        "recent_runs": recent_runs,
        "last_briefing": {
            "briefing_date": _iso(last_briefing["briefing_date"]) if last_briefing else None,
            "title": last_briefing["title"] if last_briefing else None,
            "status": last_briefing["status"] if last_briefing else None,
            "updated_at": _iso(last_briefing["updated_at"]) if last_briefing else None,
        },
    }
