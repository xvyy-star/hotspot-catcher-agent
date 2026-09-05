"""数据源健康聚合服务。

这里不额外建新表，而是复用 AgentRun.meta.source_health。
原因：
1. 每次早报任务已经记录了各平台 SUCCESS/FALLBACK/FAILED。
2. 健康页第一版只需要做最近 N 次任务的聚合。
3. 后续企业版如果要做 Prometheus / 时序库，再把这里替换成独立指标表即可。
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from time import perf_counter
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.agent.runner import CONNECTOR_REGISTRY, load_sources_config
from app.core.config import settings
from app.core.source_policy import OFFICIAL_SOURCE_CODES
from app.db.models import AgentRun, HotspotRawItem
from app.pipeline.evidence import FAKE_SOURCE_CODES, is_fallback_item as evidence_is_fallback_item, split_items_by_evidence
from app.schemas import HotspotItem


# 已从产品主线删除的源：
# - 不读取配置
# - 不注册 connector
# - 即使历史 run/raw_item 里有旧记录，也不再在采集源状态页展示
REMOVED_SOURCE_CODES = {"weibo", "zhihu", "xiaohongshu", *FAKE_SOURCE_CODES}
_LIVE_PROBE_CACHE: dict[tuple[tuple[str, ...], int, int], tuple[float, dict[str, dict[str, Any]], dict[str, Any]]] = {}


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def _load_source_configs() -> dict[str, dict[str, Any]]:
    """读取配置中的数据源元信息，保证没有运行记录时也能展示所有源。"""
    config = load_sources_config()
    result: dict[str, dict[str, Any]] = {}
    for item in config.get("sources", []):
        code = str(item.get("code") or "").strip()
        if code not in OFFICIAL_SOURCE_CODES:
            continue
        result[code] = {
            "code": code,
            "name": item.get("name") or code,
            "enabled": bool(item.get("enabled", False)),
            "weight": float(item.get("weight") or 0),
            "strategy": item.get("strategy") or "-",
            "note": item.get("note") or "",
            "max_items": int(item.get("max_items") or 0),
            "source_url": item.get("source_url") or "",
            "domains": item.get("domains") or item.get("modes") or [],
        }
    return result


def _extract_source_health(meta: Any) -> dict[str, Any]:
    """兼容早期 run.meta 直接保存 source_health 的情况。"""
    if not isinstance(meta, dict):
        return {}
    source_health = meta.get("source_health")
    if isinstance(source_health, dict):
        return source_health

    # 老版本失败记录可能直接把 {baidu: {...}, weibo: {...}} 写进 meta。
    looks_like_health = any(isinstance(v, dict) and "status" in v for v in meta.values())
    return meta if looks_like_health else {}


def _empty_source_item(source_cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        **source_cfg,
        "attempts": 0,
        "success_count": 0,
        "fallback_count": 0,
        "failed_count": 0,
        "disabled_count": 0,
        "success_rate": 0,
        "availability_rate": 0,
        "total_items": 0,
        "real_items": 0,
        "fallback_items": 0,
        "dropped_fallback_count": 0,
        "dropped_no_evidence_count": 0,
        "latest_status": "DISABLED" if not source_cfg.get("enabled") else "NO_DATA",
        "latest_run_id": None,
        "latest_run_at": None,
        "latest_error": "配置中已关闭" if not source_cfg.get("enabled") else "暂无运行记录",
        "is_stale": False,
        "age_hours": None,
        "stale_after_hours": max(1, int(settings.source_health_stale_hours or 36)),
        "last_captured_at": None,
        "raw_item_total": 0,
        "health_level": "DISABLED" if not source_cfg.get("enabled") else "UNKNOWN",
        "status_counts": {},
        "recent": [],
    }


def _judge_health_level(item: dict[str, Any]) -> str:
    if not item.get("enabled"):
        return "DISABLED"
    if item["attempts"] <= 0:
        return "UNKNOWN"
    if item.get("is_stale"):
        return "STALE"
    latest = item.get("latest_status")
    if latest == "FAILED":
        return "DOWN"
    if latest == "FALLBACK":
        return "DEGRADED"
    if item.get("success_rate", 0) >= 80:
        return "HEALTHY"
    if item.get("availability_rate", 0) >= 80:
        return "DEGRADED"
    return "UNSTABLE"


def _is_fallback_item(item: HotspotItem) -> bool:
    """判断采集结果是不是 sample 兜底。

    实时探测页必须把“真实采集”和“样例兜底”分开，否则看起来像成功，
    实际上会误导交付验收。
    """
    return evidence_is_fallback_item(item)


def _item_preview(item: HotspotItem) -> dict[str, Any]:
    """把实时采集结果压缩成前端预览字段，避免把大 JSON 全量塞到健康页。"""
    payload = item.raw_payload or {}
    return {
        "title": item.title,
        "url": item.url,
        "rank": item.rank,
        "raw_hot_score": item.raw_hot_score,
        "source_item_id": item.source_item_id,
        "category": payload.get("system_category") or (item.tags[0] if item.tags else ""),
        "is_fallback_sample": bool(payload.get("is_fallback_sample")),
        "real_source": bool(payload.get("real_source", False)),
        "has_real_evidence": bool(payload.get("has_real_evidence")) and bool(item.url),
    }


def _probe_one_source(source_cfg: dict[str, Any], *, probe_limit: int, timeout: int) -> tuple[str, dict[str, Any]]:
    """实时探测一个源：直接跑 connector.fetch()，但不写库、不生成早报。"""
    code = str(source_cfg.get("code") or "").strip()
    checked_at = datetime.utcnow()
    started = perf_counter()
    base = {
        "code": code,
        "checked_at": checked_at.isoformat(),
        "latency_ms": 0,
        "status": "UNKNOWN",
        "count": 0,
        "real_count": 0,
        "fallback_count": 0,
        "dropped_fallback_count": 0,
        "dropped_no_evidence_count": 0,
        "preview_count": 0,
        "items_preview": [],
        "error": "",
        "message": "",
    }

    try:
        if not source_cfg.get("enabled"):
            base.update(
                {
                    "status": "DISABLED",
                    "error": "配置中已关闭，未执行实时采集",
                    "message": "配置中已关闭，未执行实时采集",
                }
            )
            return code, base

        connector_cls = CONNECTOR_REGISTRY.get(code)
        if not connector_cls:
            base.update(
                {
                    "status": "FAILED",
                    "error": "未注册 connector，无法实时采集",
                    "message": "未注册 connector，无法实时采集",
                }
            )
            return code, base

        max_items = int(source_cfg.get("max_items") or probe_limit or 10)
        connector = connector_cls(
            max_items=max(1, min(max_items, probe_limit)),
            timeout=max(3, timeout),
        )
        connector.source_config = source_cfg
        items = connector.fetch()
        accepted_items, dropped_fallback_count, dropped_no_evidence_count = split_items_by_evidence(items)
        fallback_items = [item for item in items if _is_fallback_item(item)]
        preview_items = accepted_items

        status = "SUCCESS" if accepted_items else "FAILED"
        if status == "SUCCESS":
            message = f"实时采集成功：{len(accepted_items)} 条有原文链接的真实数据"
            error = ""
        elif dropped_fallback_count:
            message = f"实时采集只返回样例/模拟数据：{dropped_fallback_count} 条，已拦截"
            error = message
        elif dropped_no_evidence_count:
            message = f"实时采集返回 {dropped_no_evidence_count} 条但缺少原文链接，已拦截"
            error = message
        else:
            message = "实时采集未获取到带原文链接的真实数据"
            error = message

        base.update(
            {
                "status": status,
                "count": len(items),
                "real_count": len(accepted_items),
                "fallback_count": 0,
                "dropped_fallback_count": dropped_fallback_count,
                "dropped_no_evidence_count": dropped_no_evidence_count,
                "preview_count": len(preview_items[:5]),
                "items_preview": [_item_preview(item) for item in preview_items[:5]],
                "error": error,
                "message": message,
            }
        )
        return code, base
    except Exception as exc:  # noqa: BLE001
        base.update(
            {
                "status": "FAILED",
                "error": str(exc),
                "message": f"实时采集异常：{exc}",
            }
        )
        return code, base
    finally:
        base["latency_ms"] = round((perf_counter() - started) * 1000)


def _live_status_to_health(status: str) -> str:
    status = (status or "").upper()
    if status == "SUCCESS":
        return "HEALTHY"
    if status == "FALLBACK":
        return "DEGRADED"
    if status == "DISABLED":
        return "DISABLED"
    if status == "FAILED":
        return "DOWN"
    return "UNKNOWN"


def _attach_live_probe(
    items: dict[str, dict[str, Any]],
    source_configs: dict[str, dict[str, Any]],
    *,
    probe_limit: int,
    timeout: int,
) -> dict[str, Any]:
    """并发执行实时探测，并把结果合并进健康项。"""
    probe_limit = max(1, min(int(probe_limit or 10), 30))
    timeout = max(3, min(int(timeout or 12), 60))
    source_cfgs = list(source_configs.values())
    cache_key = (tuple(sorted(str(cfg.get("code") or "") for cfg in source_cfgs)), probe_limit, timeout)
    now_ts = perf_counter()
    cached = _LIVE_PROBE_CACHE.get(cache_key)
    cache_ttl = max(0, int(settings.live_probe_cache_seconds or 0))
    if cached and cache_ttl and now_ts - cached[0] <= cache_ttl:
        probes = {code: dict(probe) for code, probe in cached[1].items()}
        live_meta = dict(cached[2])
        live_meta["cached"] = True
        live_meta["cache_ttl_seconds"] = cache_ttl
    else:
        probes: dict[str, dict[str, Any]] = {}
        checked_at = datetime.utcnow().isoformat()

        max_workers = min(8, max(1, len(source_cfgs)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(_probe_one_source, cfg, probe_limit=probe_limit, timeout=timeout)
                for cfg in source_cfgs
            ]
            for future in as_completed(futures):
                code, probe = future.result()
                probes[code] = probe
        live_meta = {
            "enabled": True,
            "checked_at": checked_at,
            "probe_limit": probe_limit,
            "timeout": timeout,
            "total": len(probes),
            "success": sum(1 for probe in probes.values() if probe.get("status") == "SUCCESS"),
            "fallback": sum(1 for probe in probes.values() if probe.get("status") == "FALLBACK"),
            "failed": sum(1 for probe in probes.values() if probe.get("status") == "FAILED"),
            "disabled": sum(1 for probe in probes.values() if probe.get("status") == "DISABLED"),
            "dropped_fallback_count": sum(int(probe.get("dropped_fallback_count") or 0) for probe in probes.values()),
            "dropped_no_evidence_count": sum(int(probe.get("dropped_no_evidence_count") or 0) for probe in probes.values()),
            "cached": False,
            "cache_ttl_seconds": cache_ttl,
        }
        if cache_ttl:
            _LIVE_PROBE_CACHE[cache_key] = (now_ts, {code: dict(probe) for code, probe in probes.items()}, dict(live_meta))

    for code, probe in probes.items():
        item = items.get(code)
        if not item:
            continue
        status = str(probe.get("status") or "UNKNOWN").upper()
        item["live_probe"] = probe
        item["live_checked_at"] = probe.get("checked_at")
        item["live_status"] = status
        item["live_real_items"] = int(probe.get("real_count") or 0)
        item["live_fallback_items"] = int(probe.get("fallback_count") or 0)
        item["live_dropped_no_evidence_items"] = int(probe.get("dropped_no_evidence_count") or 0)
        item["live_latency_ms"] = int(probe.get("latency_ms") or 0)
        # 打开实时模式时，表格的健康等级优先表达“现在是否能抓到真实数据”。
        item["health_level"] = _live_status_to_health(status)
        item["latest_status"] = status
        item["latest_error"] = probe.get("message") or probe.get("error") or "-"

    return live_meta


def get_source_health_report(
    db: Session,
    limit: int = 30,
    *,
    live: bool = False,
    probe_limit: int = 10,
    timeout: int = 12,
) -> dict[str, Any]:
    """聚合最近 N 次 AgentRun，生成数据源健康报告。"""
    limit = max(1, min(int(limit or 30), 100))
    source_configs = _load_source_configs()
    items: dict[str, dict[str, Any]] = {code: _empty_source_item(cfg) for code, cfg in source_configs.items()}

    # 原始采集表只查轻量聚合字段，用于展示“最后一次真实入库时间”。
    raw_stats = db.execute(
        select(
            HotspotRawItem.source_code,
            func.count(HotspotRawItem.id),
            func.max(HotspotRawItem.captured_at),
        ).group_by(HotspotRawItem.source_code)
    ).all()
    for source_code, total, last_captured_at in raw_stats:
        if source_code not in OFFICIAL_SOURCE_CODES:
            continue
        if source_code not in items:
            items[source_code] = _empty_source_item(
                {
                    "code": source_code,
                    "name": source_code,
                    "enabled": True,
                    "weight": 0,
                    "strategy": "unknown",
                    "note": "运行记录中出现，但配置文件中不存在",
                    "max_items": 0,
                }
            )
        items[source_code]["raw_item_total"] = int(total or 0)
        items[source_code]["last_captured_at"] = _iso(last_captured_at)

    runs = list(
        db.execute(
            select(AgentRun)
            .order_by(desc(AgentRun.started_at))
            .limit(limit)
        ).scalars()
    )

    for run in runs:
        source_health = _extract_source_health(run.meta)
        if not source_health:
            continue
        for code, meta in source_health.items():
            if code not in OFFICIAL_SOURCE_CODES:
                continue
            if not isinstance(meta, dict):
                continue
            if code not in items:
                items[code] = _empty_source_item(
                    {
                        "code": code,
                        "name": code,
                        "enabled": True,
                        "weight": 0,
                        "strategy": "unknown",
                        "note": "运行记录中出现，但配置文件中不存在",
                        "max_items": 0,
                    }
                )

            item = items[code]
            status = str(meta.get("status") or "UNKNOWN").upper()
            item["attempts"] += 1
            if status == "SUCCESS":
                item["success_count"] += 1
            elif status == "FALLBACK":
                item["fallback_count"] += 1
            elif status == "FAILED":
                item["failed_count"] += 1
            elif status == "DISABLED":
                item["disabled_count"] += 1

            item["total_items"] += int(meta.get("count") or 0)
            item["real_items"] += int(meta.get("real_count") or 0)
            item["fallback_items"] += int(meta.get("fallback_count") or 0)
            item["dropped_fallback_count"] += int(meta.get("dropped_fallback_count") or 0)
            item["dropped_no_evidence_count"] = item.get("dropped_no_evidence_count", 0) + int(meta.get("dropped_no_evidence_count") or 0)

            if item["latest_run_id"] is None:
                item["latest_status"] = status
                item["latest_run_id"] = run.run_id
                item["latest_run_at"] = _iso(run.started_at)
                if meta.get("error"):
                    item["latest_error"] = str(meta.get("error"))
                elif status == "FALLBACK":
                    item["latest_error"] = "历史记录含样例/模拟兜底；当前版本已改为拦截"
                elif status == "FAILED":
                    item["latest_error"] = run.error_message or "采集失败，且没有带原文链接的真实数据"
                else:
                    item["latest_error"] = "-"

            if len(item["recent"]) < 8:
                item["recent"].append(
                    {
                        "run_id": run.run_id,
                        "run_at": _iso(run.started_at),
                        "status": status,
                        "count": int(meta.get("count") or 0),
                        "real_count": int(meta.get("real_count") or 0),
                        "fallback_count": int(meta.get("fallback_count") or 0),
                        "dropped_fallback_count": int(meta.get("dropped_fallback_count") or 0),
                        "dropped_no_evidence_count": int(meta.get("dropped_no_evidence_count") or 0),
                        "error": meta.get("error") or None,
                    }
                )

    for item in items.values():
        attempts = item["attempts"]
        latest_run_at = item.get("latest_run_at")
        if latest_run_at:
            try:
                latest_dt = datetime.fromisoformat(str(latest_run_at).replace("Z", "+00:00")).replace(tzinfo=None)
                age_hours = max(0.0, (datetime.utcnow() - latest_dt).total_seconds() / 3600)
                item["age_hours"] = round(age_hours, 1)
                item["is_stale"] = age_hours > float(item["stale_after_hours"])
                if item["is_stale"] and item.get("latest_error") in {None, "-"}:
                    item["latest_error"] = f"最近采集记录已超过 {item['stale_after_hours']} 小时，请重新运行任务"
            except (TypeError, ValueError):
                item["is_stale"] = True
        item["success_rate"] = round(item["success_count"] / attempts * 100, 1) if attempts else 0
        item["availability_rate"] = item["success_rate"]
        item["status_counts"] = dict(
            Counter({
                "SUCCESS": item["success_count"],
                "FALLBACK": item["fallback_count"],
                "FAILED": item["failed_count"],
                "DISABLED": item["disabled_count"],
            })
        )
        item["health_level"] = _judge_health_level(item)

    live_probe_meta: dict[str, Any] = {"enabled": False}
    if live:
        live_probe_meta = _attach_live_probe(
            items,
            source_configs,
            probe_limit=probe_limit,
            timeout=timeout,
        )

    rows = sorted(
        items.values(),
        key=lambda x: (
            1 if x["health_level"] == "DOWN" else 2 if x["health_level"] in {"DEGRADED", "STALE"} else 3 if x["health_level"] == "UNSTABLE" else 4,
            -x.get("attempts", 0),
            x.get("code", ""),
        ),
    )
    enabled_rows = [row for row in rows if row.get("enabled")]
    avg_success_rate = round(sum(row["success_rate"] for row in enabled_rows) / len(enabled_rows), 1) if enabled_rows else 0
    latest_run_at = max((_iso(run.started_at) for run in runs if run.started_at), default=None)

    return {
        "window_run_limit": limit,
        "recent_run_count": len(runs),
        "latest_run_at": latest_run_at,
        "total_sources": len(rows),
        "enabled_sources": len(enabled_rows),
        "healthy_sources": sum(1 for row in rows if row["health_level"] == "HEALTHY"),
        "degraded_sources": sum(1 for row in rows if row["health_level"] in {"DEGRADED", "UNSTABLE", "STALE"}),
        "down_sources": sum(1 for row in rows if row["health_level"] == "DOWN"),
        "stale_sources": sum(1 for row in rows if row["health_level"] == "STALE"),
        "unknown_sources": sum(1 for row in rows if row["health_level"] == "UNKNOWN"),
        "avg_success_rate": avg_success_rate,
        "live_probe": live_probe_meta,
        "items": rows,
    }
