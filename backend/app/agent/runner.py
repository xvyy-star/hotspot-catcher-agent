"""热点捕手 Agent 编排器。

这个文件是项目核心：它把采集器、清洗、去重、评分、分析、早报生成、落库串成一个完整任务。
它负责把采集、去重、评分、RAG、分析、简报和推送串成一次可观测任务。
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.arxiv_ai import ArxivAIConnector
from app.connectors.public_apis import GitHubAPIConnector, HuggingFaceConnector, DevCommunityConnector
from app.connectors.hackernews import HackerNewsConnector
from app.core.config import settings
from app.core.source_policy import OFFICIAL_SOURCE_CODES
from app.db.models import AgentRun
from app.pipeline.analysis import analyze_events
from app.pipeline.briefing import build_briefing
from app.pipeline.deduplicate import deduplicate_items
from app.pipeline.evidence import is_fallback_item as evidence_is_fallback_item, split_items_by_evidence
from app.pipeline.rag_enrichment import enrich_events_with_rag
from app.pipeline.relevance import filter_events_for_product_focus
from app.pipeline.scoring import score_events
from app.schemas import BriefingDTO, GenerateBriefingResponse, HotspotItem
from app.storage.repository import create_run, finish_run, save_briefing, save_raw_items, upsert_events
from app.services.model_provider_service import get_enabled_providers
from app.services.push_service import push_briefing

logger = logging.getLogger(__name__)

CONNECTOR_REGISTRY = {
    "github": GitHubAPIConnector,
    "huggingface": HuggingFaceConnector,
    "devto": DevCommunityConnector,
    "hackernews": HackerNewsConnector,
    "arxiv_ai": ArxivAIConnector,
}


def load_sources_config() -> dict[str, Any]:
    """读取热点源配置。"""
    with open(settings.sources_config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    # 前端“QQ 机器人推送配置页”会写入 config/push.local.json。
    # 这里在运行任务前合并它，避免手改 sources.example.yml。
    try:
        from app.services.push_config_service import load_push_config

        config["push"] = load_push_config(include_env=True, mask_token=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取本地推送配置失败，继续使用 sources 配置: %s", exc)
    return config


def _as_list(value: Any) -> list[str]:
    """把 YAML 里的字符串/数组统一转成字符串数组。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _source_matches_focus_modes(source_cfg: dict[str, Any], focus_modes: set[str]) -> bool:
    """判断数据源是否属于当前产品模式。

    例如默认模式是：
    - computer_industry：计算机行业热点
    - ai_product_intelligence：AI 产品 / 开源技术 / 科技产业热点

    如果没有配置 focus_modes，就保持旧逻辑：所有 enabled 源都参与。
    """
    if not focus_modes:
        return True
    source_domains = set(_as_list(source_cfg.get("domains") or source_cfg.get("modes")))
    if not source_domains:
        return True
    return bool(source_domains & focus_modes)


def build_connectors(config: dict[str, Any]):
    """根据配置创建采集器实例。

    好处：启停平台、修改采集数量都不需要改代码。
    """
    connectors = []
    briefing_cfg = config.get("briefing", {})
    focus_modes = set(_as_list(briefing_cfg.get("focus_modes") or briefing_cfg.get("focus_mode")))
    for source in config.get("sources", []):
        if source.get("code") not in OFFICIAL_SOURCE_CODES:
            raise ValueError(f"Unsupported source: {source.get('code')}")
        if not source.get("enabled", False):
            continue
        if not _source_matches_focus_modes(source, focus_modes):
            logger.info("热点源不属于当前 focus_modes，跳过: %s", source.get("code"))
            continue
        code = source.get("code")
        cls = CONNECTOR_REGISTRY.get(code)
        if not cls:
            logger.warning("未知热点源，跳过: %s", code)
            continue
        connector = cls(max_items=int(source.get("max_items", 50)), timeout=int(source.get("timeout", 10)))
        # 动态挂载配置，后续生成 source_health 时可以带上来源 URL、领域、策略等信息。
        connector.source_config = source
        connectors.append(connector)
    return connectors


def _is_fallback_item(item: HotspotItem) -> bool:
    """判断某条数据是否为本地样例兜底。"""
    return evidence_is_fallback_item(item)


def _build_source_health(
    *,
    connector: Any,
    fetched_items: list[HotspotItem],
    accepted_items: list[HotspotItem],
    strict_real_mode: bool,
    dropped_fallback_count: int = 0,
    dropped_no_evidence_count: int = 0,
    error: str | None = None,
) -> dict[str, Any]:
    """生成单个数据源的健康信息。

    关键原则：FALLBACK 不能被伪装成 SUCCESS；strict_real_mode 开启时，样例兜底
    会被丢弃，不进入 raw_item、不进入 event、更不会进入早报。
    """
    source_cfg = getattr(connector, "source_config", {}) or {}
    fallback_count = sum(1 for item in fetched_items if _is_fallback_item(item))
    real_candidate_count = max(0, len(fetched_items) - fallback_count)
    accepted_real_count = sum(1 for item in accepted_items if not _is_fallback_item(item))
    accepted_fallback_count = sum(1 for item in accepted_items if _is_fallback_item(item))
    dropped_fallback_count = dropped_fallback_count or max(0, fallback_count - accepted_fallback_count)
    dropped_no_evidence_count = dropped_no_evidence_count or max(0, real_candidate_count - accepted_real_count)

    if error:
        status = "FAILED"
    elif accepted_real_count > 0:
        status = "SUCCESS"
    else:
        status = "FAILED"

    if not error and status == "FAILED":
        if dropped_fallback_count > 0:
            error = "真实模式已开启：样例/模拟数据已拦截，未进入早报"
        elif dropped_no_evidence_count > 0:
            error = "真实模式已开启：缺少 item 级原文链接的数据已拦截，未进入早报"
        else:
            error = "未采集到带原文链接的真实数据"

    return {
        "status": status,
        "count": len(accepted_items),
        "fetched_count": len(fetched_items),
        "real_count": accepted_real_count,
        "real_candidate_count": real_candidate_count,
        "fallback_count": accepted_fallback_count,
        "dropped_fallback_count": dropped_fallback_count,
        "dropped_no_evidence_count": dropped_no_evidence_count,
        "source_url": source_cfg.get("source_url") or source_cfg.get("url") or "",
        "strategy": source_cfg.get("strategy") or "",
        "domains": _as_list(source_cfg.get("domains") or source_cfg.get("modes")),
        "real_data_policy": "STRICT_REAL_WITH_ITEM_URL",
        "evidence_policy": "ITEM_LEVEL_HTTP_URL_REQUIRED",
        "error": error,
    }


def _build_data_quality_report(source_health: dict[str, Any], *, config: dict[str, Any], real_item_count: int) -> dict[str, Any]:
    """计算整次任务的数据可信度，用于运行记录、健康告警和交付验收。"""
    briefing_cfg = config.get("briefing", {})
    minimum_real_source_count = int(briefing_cfg.get("minimum_real_source_count", 1))
    minimum_real_item_count = int(briefing_cfg.get("minimum_real_item_count", 1))
    success_sources = [code for code, meta in source_health.items() if meta.get("status") == "SUCCESS" and int(meta.get("real_count") or 0) > 0]
    status = "PASS" if len(success_sources) >= minimum_real_source_count and real_item_count >= minimum_real_item_count else "LOW_REAL_COVERAGE"
    return {
        "status": status,
        "strict_real_mode": True,
        "evidence_policy": "ITEM_LEVEL_HTTP_URL_REQUIRED",
        "real_source_count": len(success_sources),
        "real_item_count": real_item_count,
        "dropped_fallback_count": sum(int(meta.get("dropped_fallback_count") or 0) for meta in source_health.values()),
        "dropped_no_evidence_count": sum(int(meta.get("dropped_no_evidence_count") or 0) for meta in source_health.values()),
        "minimum_real_source_count": minimum_real_source_count,
        "minimum_real_item_count": minimum_real_item_count,
        "success_sources": success_sources,
    }


def _update_run_progress(db: Session, run_id: str | None, *, progress: int, stage: str) -> None:
    """长任务阶段进度回写，供前端轮询展示。"""
    if not run_id:
        return
    row = db.execute(select(AgentRun).where(AgentRun.run_id == run_id)).scalar_one_or_none()
    if not row:
        return
    row.meta = {**(row.meta or {}), "progress": max(0, min(99, int(progress))), "stage": stage}
    db.commit()


def run_daily_briefing(
    db: Session,
    target_date: date | None = None,
    trigger: str = "manual",
    run_id: str | None = None,
    initial_meta: dict[str, Any] | None = None,
) -> GenerateBriefingResponse:
    """执行一次今日早报任务。"""
    # trigger 写进 run_id 和 meta，方便任务中心区分“手动触发”和“自动调度”。
    safe_trigger = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in trigger)[:24] or "manual"
    run_id = run_id or f"{safe_trigger}-{target_date or date.today()}-{uuid.uuid4().hex[:8]}"
    create_run(db, run_id, status="RUNNING", meta=initial_meta)
    db.commit()

    total_raw = 0
    total_events = 0
    source_health: dict[str, Any] = {}
    try:
        _update_run_progress(db, run_id, progress=12, stage="load_config")
        config = load_sources_config()
        briefing_cfg = config.get("briefing", {})
        target_industry = briefing_cfg.get("target_industry", "通用行业")
        deep_limit = int(briefing_cfg.get("llm_deep_analysis_limit", 30))
        knowledge_cfg = config.get("knowledge", {}) or {}
        rag_enabled = _as_bool(knowledge_cfg.get("rag_enrichment_enabled"), True)
        rag_limit = int(knowledge_cfg.get("rag_enrichment_top_event_limit", 10))
        rag_top_k = int(knowledge_cfg.get("rag_enrichment_top_k", 3))
        # 全局真实数据闸门：无论配置是否误改，都不允许 sample/mock/fallback 或无原文链接的数据进入早报。
        strict_real_mode = True
        model_providers = get_enabled_providers(db)

        connectors = build_connectors(config)
        all_items: list[HotspotItem] = []

        # 逐个平台采集。MVP 先串行，稳定后再并发。
        _update_run_progress(db, run_id, progress=20, stage="fetch_sources")
        for connector in connectors:
            try:
                fetched_items = connector.fetch()
                accepted_items, dropped_fallback_count, dropped_no_evidence_count = split_items_by_evidence(fetched_items)
                source_health[connector.source_code] = _build_source_health(
                    connector=connector,
                    fetched_items=fetched_items,
                    accepted_items=accepted_items,
                    strict_real_mode=strict_real_mode,
                    dropped_fallback_count=dropped_fallback_count,
                    dropped_no_evidence_count=dropped_no_evidence_count,
                )
                all_items.extend(accepted_items)
            except Exception as exc:  # noqa: BLE001
                # 理论上子类会吞异常，这里再兜底一次，确保单源失败不拖垮任务。
                logger.exception("热点源采集失败: %s", connector.source_code)
                source_health[connector.source_code] = _build_source_health(
                    connector=connector,
                    fetched_items=[],
                    accepted_items=[],
                    strict_real_mode=strict_real_mode,
                    error=str(exc),
                )

        total_raw = len(all_items)
        _update_run_progress(db, run_id, progress=36, stage="save_raw_items")
        real_item_count = sum(int(meta.get("real_count") or 0) for meta in source_health.values())
        data_quality = _build_data_quality_report(source_health, config=config, real_item_count=real_item_count)
        raw_ids = save_raw_items(db, all_items)
        # 将 DB id 回填到 raw_payload，方便事件表追溯。
        for item, raw_id in zip(all_items, raw_ids):
            item.raw_payload = {**(item.raw_payload or {}), "_db_id": raw_id}

        _update_run_progress(db, run_id, progress=48, stage="deduplicate_and_score")
        events = filter_events_for_product_focus(deduplicate_items(all_items))
        events = score_events(events)
        _update_run_progress(db, run_id, progress=58, stage="rag_enrichment")
        events = enrich_events_with_rag(
            events,
            db=db,
            target_industry=target_industry,
            enabled=rag_enabled,
            limit=rag_limit,
            top_k=rag_top_k,
        )
        _update_run_progress(db, run_id, progress=68, stage="analysis")
        events = analyze_events(
            events,
            target_industry=target_industry,
            limit=deep_limit,
            providers=model_providers,
            db=db,
            run_id=run_id,
        )
        total_events = len(events)

        _update_run_progress(db, run_id, progress=78, stage="persist_events")
        upsert_events(db, events)
        _update_run_progress(db, run_id, progress=86, stage="build_briefing")
        briefing = build_briefing(events, target_date or date.today(), source_health)
        if data_quality["status"] == "LOW_REAL_COVERAGE" and briefing.status == "SUCCESS":
            briefing.status = "LOW_REAL_COVERAGE"
        save_briefing(db, briefing)

        # 推送与主流程解耦：即使 QQ 机器人未启动，默认也只记录失败，不影响早报生成。
        _update_run_progress(db, run_id, progress=92, stage="push")
        push_result = push_briefing(
            db,
            briefing=briefing,
            run_id=run_id,
            push_cfg=config.get("push", {}),
        )
        run_meta = {
            **(initial_meta or {}),
            "trigger": trigger,
            "target_date": (target_date or date.today()).isoformat(),
            "progress": 100,
            "stage": "finished",
            "source_health": source_health,
            "data_quality": data_quality,
            "push": push_result,
        }
        allow_partial_success = bool(config.get("push", {}).get("allow_partial_success", True))
        if push_result.get("status") == "FAILED" and not allow_partial_success:
            raise RuntimeError(f"早报推送失败：{push_result.get('message')}")

        finish_run(db, run_id, "SUCCESS", total_raw, total_events, meta=run_meta)
        db.commit()
        message = "今日早报生成成功" if data_quality["status"] == "PASS" else "今日早报已生成，但真实数据覆盖不足，请查看数据源健康页"
        return GenerateBriefingResponse(run_id=run_id, status="SUCCESS", briefing=briefing, message=message)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        finish_run(
            db,
            run_id,
            "FAILED",
            total_raw,
            total_events,
            error_message=str(exc),
            meta={
                **(initial_meta or {}),
                "trigger": trigger,
                "target_date": (target_date or date.today()).isoformat(),
                "progress": 100,
                "stage": "failed",
                "source_health": source_health,
            },
        )
        db.commit()
        logger.exception("今日早报任务失败")
        return GenerateBriefingResponse(run_id=run_id, status="FAILED", message=str(exc))
