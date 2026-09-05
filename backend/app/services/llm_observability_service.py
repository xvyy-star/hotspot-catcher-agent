"""LLM 调用缓存与可观测性服务。

企业级 Agent 不能只追求“能调用模型”，还必须回答三个问题：
1. 成本：哪些结果可以复用，避免重复烧 Token？
2. 稳定性：哪个模型失败率高、延迟高？
3. 可解释：一条热点到底是模型分析、缓存命中，还是规则兜底？
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from sqlalchemy import case, desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AIModelProvider, LLMAnalysisCache, LLMCallLog
from app.pipeline.langchain_analysis import HotspotAnalysisResult
from app.schemas import HotspotEventDTO

PROMPT_VERSION = "hotspot-analysis-v2-topic-first"
_COST_QUANTUM = Decimal("0.0000000001")
_TOKENS_PER_MILLION = Decimal("1000000")


def _non_negative_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _normalize_usage(usage: dict[str, Any] | None) -> dict[str, int | None]:
    data = usage or {}
    prompt_tokens = _non_negative_int(data.get("prompt_tokens", data.get("input_tokens")))
    completion_tokens = _non_negative_int(data.get("completion_tokens", data.get("output_tokens")))
    total_tokens = _non_negative_int(data.get("total_tokens"))
    if total_tokens is None and (prompt_tokens is not None or completion_tokens is not None):
        total_tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _decimal_or_zero(value: Any) -> Decimal:
    try:
        return max(Decimal("0"), Decimal(str(value or 0)))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def calculate_estimated_cost(
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    provider: AIModelProvider | None,
) -> Decimal:
    """Calculate one call's USD cost using the provider prices at log time."""
    input_rate = _decimal_or_zero(getattr(provider, "input_cost_per_million", 0))
    output_rate = _decimal_or_zero(getattr(provider, "output_cost_per_million", 0))
    raw_cost = (
        Decimal(max(0, int(prompt_tokens or 0))) * input_rate
        + Decimal(max(0, int(completion_tokens or 0))) * output_rate
    ) / _TOKENS_PER_MILLION
    return raw_cost.quantize(_COST_QUANTUM, rounding=ROUND_HALF_UP)


def _cost_as_float(value: Any) -> float:
    return float(_decimal_or_zero(value).quantize(_COST_QUANTUM, rounding=ROUND_HALF_UP))


def provider_identity(provider: AIModelProvider | None) -> dict[str, str | None]:
    """统一封装模型身份，便于缓存和日志复用。"""
    if provider:
        return {
            "provider_code": provider.code,
            "provider_name": provider.name,
            "model": provider.model,
        }
    return {
        "provider_code": "env-default",
        "provider_name": "环境变量默认模型",
        "model": settings.ai_model,
    }


def build_prompt_fingerprint(event: HotspotEventDTO, target_industry: str) -> str:
    """构造稳定的 Prompt 指纹。

    只放会影响分析结果的字段，不放 captured_at / DB id 这类每次运行都会变化的字段。
    这样同一个热点重复生成早报时，可以直接命中缓存。
    """
    payload = {
        "version": PROMPT_VERSION,
        "target_industry": target_industry,
        "event_key": event.event_key,
        "title": event.title,
        "sources": sorted(event.source_codes),
        # 热度分会随榜单刷新轻微波动，不纳入缓存指纹；
        # 这样同一热点在多次生成早报时能复用分析结论。
        "texts": [(item.content or item.title or "")[:500] for item in event.items[:5]],
        "tags": sorted({tag for item in event.items for tag in item.tags[:3]}),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_cache_key(event: HotspotEventDTO, target_industry: str, provider: AIModelProvider | None) -> tuple[str, str]:
    """返回 cache_key 和 prompt_hash。"""
    prompt_hash = build_prompt_fingerprint(event, target_industry)
    identity = provider_identity(provider)
    raw = json.dumps(
        {
            "prompt_hash": prompt_hash,
            "provider_code": identity["provider_code"],
            "model": identity["model"],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest(), prompt_hash


def get_cached_analysis(db: Session, cache_key: str) -> HotspotAnalysisResult | None:
    """读取缓存并回写命中次数。"""
    row = db.execute(select(LLMAnalysisCache).where(LLMAnalysisCache.cache_key == cache_key)).scalar_one_or_none()
    if not row or not row.result_json:
        return None
    row.hit_count = int(row.hit_count or 0) + 1
    row.last_hit_at = datetime.utcnow()
    return HotspotAnalysisResult.model_validate(row.result_json)


def save_analysis_cache(
    db: Session,
    *,
    event: HotspotEventDTO,
    target_industry: str,
    provider: AIModelProvider | None,
    cache_key: str,
    prompt_hash: str,
    result: HotspotAnalysisResult,
) -> None:
    """保存模型分析结果缓存。"""
    identity = provider_identity(provider)
    existing = db.execute(select(LLMAnalysisCache).where(LLMAnalysisCache.cache_key == cache_key)).scalar_one_or_none()
    payload = result.model_dump(mode="json")
    if existing:
        existing.result_json = payload
        existing.title = event.title
        existing.target_industry = target_industry
        existing.provider_code = identity["provider_code"]
        existing.provider_name = identity["provider_name"]
        existing.model = identity["model"]
        return

    db.add(
        LLMAnalysisCache(
            cache_key=cache_key,
            prompt_hash=prompt_hash,
            event_key=event.event_key,
            title=event.title,
            target_industry=target_industry,
            provider_code=identity["provider_code"],
            provider_name=identity["provider_name"],
            model=identity["model"],
            result_json=payload,
        )
    )


def log_llm_call(
    db: Session,
    *,
    run_id: str | None,
    event: HotspotEventDTO,
    provider: AIModelProvider | None,
    status: str,
    latency_ms: int | None,
    cache_hit: bool = False,
    prompt_hash: str | None = None,
    cache_key: str | None = None,
    error_message: str | None = None,
    usage: dict[str, Any] | None = None,
) -> None:
    """记录一次模型调用或缓存命中。"""
    identity = provider_identity(provider)
    normalized_usage = _normalize_usage(usage)
    estimated_cost = calculate_estimated_cost(
        prompt_tokens=normalized_usage["prompt_tokens"],
        completion_tokens=normalized_usage["completion_tokens"],
        provider=provider,
    )
    db.add(
        LLMCallLog(
            run_id=run_id,
            event_key=event.event_key,
            title=event.title,
            provider_code=identity["provider_code"],
            provider_name=identity["provider_name"],
            model=identity["model"],
            status=status,
            cache_hit=cache_hit,
            latency_ms=latency_ms,
            prompt_hash=prompt_hash,
            cache_key=cache_key,
            error_message=(error_message or "")[:1000] or None,
            prompt_tokens=normalized_usage["prompt_tokens"],
            completion_tokens=normalized_usage["completion_tokens"],
            total_tokens=normalized_usage["total_tokens"],
            estimated_cost=estimated_cost,
        )
    )


def get_llm_stats(db: Session, limit: int = 50) -> dict[str, Any]:
    """聚合模型调用统计，前端统计页直接消费。"""
    success_case = case((LLMCallLog.status.in_(("SUCCESS", "CACHE_HIT")), 1), else_=0)
    failed_case = case((LLMCallLog.status == "FAILED", 1), else_=0)
    cache_hit_case = case(
        (or_(LLMCallLog.cache_hit.is_(True), LLMCallLog.status == "CACHE_HIT"), 1),
        else_=0,
    )
    measured_latency = case(
        (LLMCallLog.cache_hit.is_(False), LLMCallLog.latency_ms),
        else_=None,
    )

    totals = db.execute(
        select(
            func.count(LLMCallLog.id).label("total_calls"),
            func.coalesce(func.sum(success_case), 0).label("success_count"),
            func.coalesce(func.sum(failed_case), 0).label("failed_count"),
            func.coalesce(func.sum(cache_hit_case), 0).label("cache_hit_count"),
            func.avg(measured_latency).label("avg_latency_ms"),
            func.coalesce(func.sum(LLMCallLog.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(LLMCallLog.estimated_cost), 0).label("total_estimated_cost"),
        )
    ).mappings().one()
    total_calls = int(totals["total_calls"] or 0)
    success_count = int(totals["success_count"] or 0)
    failed_count = int(totals["failed_count"] or 0)
    cache_hit_count = int(totals["cache_hit_count"] or 0)
    avg_latency_ms = round(float(totals["avg_latency_ms"] or 0), 1)
    total_tokens = int(totals["total_tokens"] or 0)
    total_estimated_cost = _decimal_or_zero(totals["total_estimated_cost"])

    provider_rows = db.execute(
        select(
            LLMCallLog.provider_code,
            func.max(LLMCallLog.provider_name).label("provider_name"),
            LLMCallLog.model,
            func.count(LLMCallLog.id).label("total_calls"),
            func.coalesce(func.sum(success_case), 0).label("success_count"),
            func.coalesce(func.sum(failed_case), 0).label("failed_count"),
            func.coalesce(func.sum(cache_hit_case), 0).label("cache_hit_count"),
            func.avg(measured_latency).label("avg_latency_ms"),
            func.coalesce(func.sum(LLMCallLog.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(LLMCallLog.estimated_cost), 0).label("total_estimated_cost"),
        )
        .group_by(LLMCallLog.provider_code, LLMCallLog.model)
        .order_by(desc("total_calls"), desc("success_count"))
    ).mappings().all()
    provider_stats = []
    for row in provider_rows:
        provider_total = int(row["total_calls"] or 0)
        provider_success = int(row["success_count"] or 0)
        provider_stats.append(
            {
                "provider_code": row["provider_code"],
                "provider_name": row["provider_name"],
                "model": row["model"],
                "total_calls": provider_total,
                "success_count": provider_success,
                "failed_count": int(row["failed_count"] or 0),
                "cache_hit_count": int(row["cache_hit_count"] or 0),
                "avg_latency_ms": round(float(row["avg_latency_ms"] or 0), 1),
                "total_tokens": int(row["total_tokens"] or 0),
                "total_estimated_cost": _cost_as_float(row["total_estimated_cost"]),
                "success_rate": round(provider_success / provider_total * 100, 1) if provider_total else 0,
            }
        )

    recent_limit = max(1, min(int(limit), 500))
    recent_rows = list(
        db.execute(
            select(LLMCallLog)
            .order_by(desc(LLMCallLog.created_at), desc(LLMCallLog.id))
            .limit(recent_limit)
        ).scalars()
    )
    recent_calls = [
        {
            "id": row.id,
            "run_id": row.run_id,
            "event_key": row.event_key,
            "title": row.title,
            "provider_code": row.provider_code,
            "provider_name": row.provider_name,
            "model": row.model,
            "status": row.status,
            "cache_hit": row.cache_hit,
            "latency_ms": row.latency_ms,
            "error_message": row.error_message,
            "prompt_tokens": row.prompt_tokens,
            "completion_tokens": row.completion_tokens,
            "total_tokens": row.total_tokens,
            "estimated_cost": _cost_as_float(row.estimated_cost),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in recent_rows
    ]

    return {
        "total_calls": total_calls,
        "success_count": success_count,
        "failed_count": failed_count,
        "cache_hit_count": cache_hit_count,
        "avg_latency_ms": avg_latency_ms,
        "success_rate": round(success_count / total_calls * 100, 1) if total_calls else 0,
        "total_tokens": total_tokens,
        "total_estimated_cost": _cost_as_float(total_estimated_cost),
        "provider_stats": provider_stats,
        "recent_calls": recent_calls,
    }
