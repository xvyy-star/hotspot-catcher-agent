"""生产交付就绪检查服务。

这是面向上线前验收的检查单，不只是 /health：
- 检查安全默认值、真实数据证据链、采集源、模型/RAG、运维自动化和交付资产。
- 返回可直接给前端数据大屏展示的阻塞项、警告项和修复建议。
- 只输出脱敏证据，不泄露 token、password、API key。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.agent.runner import load_sources_config
from app.core.config import PROJECT_ROOT, settings
from app.db.models import AIModelProvider, AgentRun, DailyBriefing, HotspotEvent, HotspotRawItem, LLMCallLog
from app.pipeline.evidence import FAKE_SOURCE_CODES, is_http_url
from app.core.time import business_now_naive, utc_now_iso
from app.services.llm_observability_service import get_llm_stats
from app.services.push_config_service import load_push_config
from app.services.scheduler_service import load_scheduler_config
from app.services.source_health_service import get_source_health_report
from app.services.system_log_service import get_log_summary


_SEVERITY_RANK = {"CRITICAL": 5, "HIGH": 4, "MEDIUM": 3, "LOW": 2, "INFO": 1}
_PENALTY = {
    ("FAIL", "CRITICAL"): 25,
    ("FAIL", "HIGH"): 18,
    ("FAIL", "MEDIUM"): 12,
    ("FAIL", "LOW"): 8,
    ("WARN", "HIGH"): 10,
    ("WARN", "MEDIUM"): 6,
    ("WARN", "LOW"): 3,
    ("WARN", "INFO"): 1,
}
_DEFAULT_ADMIN_TOKENS = {"", "dev-admin-token", "admin-token", "changeme", "change-me"}
_DEFAULT_PASSWORDS = {"", "admin", "admin123", "admin123456", "password", "123456"}
_DEFAULT_APP_SECRETS = {"", "dev-secret-change-me", "dev-admin-token", "changeme", "change-me"}
_DEFAULT_DB_PASSWORDS = {"", "root", "root123456", "hotspot", "hotspot123", "password", "changeme", "change-me"}


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def _env_present(name: str) -> bool:
    return bool(str(os.getenv(name, "")).strip())


def _is_weak_secret(value: str | None, defaults: set[str], *, min_len: int = 24) -> bool:
    raw = str(value or "").strip()
    return raw.lower() in {item.lower() for item in defaults} or len(raw) < min_len


def _is_local_origin(origin: str) -> bool:
    parsed = urlparse(origin)
    host = parsed.hostname or origin.split(":")[0]
    return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _database_password_is_weak(database_url: str) -> bool:
    try:
        password = unquote(urlparse(database_url).password or "")
    except ValueError:
        return True
    return password.strip().lower() in _DEFAULT_DB_PASSWORDS or len(password) < 12


def _safe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return []


def _safe_source_codes(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part for part in value.replace(",", " ").split() if part.strip()]
    return []


def _safe_int_ids(value: Any) -> list[int]:
    ids: list[int] = []
    for item in _safe_source_codes(value):
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _raw_has_real_evidence(row: HotspotRawItem) -> bool:
    payload = row.raw_payload if isinstance(row.raw_payload, dict) else {}
    source = str(row.source_code or "").strip().lower()
    if source in FAKE_SOURCE_CODES:
        return False
    if payload.get("is_fallback_sample") or payload.get("mock") or payload.get("fake"):
        return False
    return is_http_url(row.url)


def _item(
    *,
    category: str,
    code: str,
    title: str,
    status: str,
    severity: str,
    description: str,
    evidence: str = "",
    action: str = "",
) -> dict[str, Any]:
    return {
        "category": category,
        "code": code,
        "title": title,
        "status": status,
        "severity": severity,
        "description": description,
        "evidence": evidence,
        "action": action,
    }


def _category(code: str, name: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    fail_count = sum(1 for item in items if item["status"] == "FAIL")
    warn_count = sum(1 for item in items if item["status"] == "WARN")
    pass_count = sum(1 for item in items if item["status"] == "PASS")
    penalty = sum(_PENALTY.get((item["status"], item["severity"]), 0) for item in items)
    status = "FAIL" if fail_count else "WARN" if warn_count else "PASS"
    return {
        "code": code,
        "name": name,
        "status": status,
        "score": max(0, min(100, 100 - penalty)),
        "summary": f"{pass_count} 项通过 / {warn_count} 项警告 / {fail_count} 项阻塞",
        "passed": pass_count,
        "warnings": warn_count,
        "blockers": fail_count,
        "items": items,
    }


def _latest_run(db: Session, *, require_data: bool = False) -> AgentRun | None:
    stmt = select(AgentRun)
    if require_data:
        stmt = stmt.where(AgentRun.status == "SUCCESS", AgentRun.total_raw > 0, AgentRun.total_events > 0)
    return db.execute(stmt.order_by(desc(AgentRun.started_at)).limit(1)).scalar_one_or_none()


def _build_security_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    category = "security"

    items.append(
        _item(
            category=category,
            code="api_auth_enabled",
            title="管理 API 鉴权",
            status="PASS" if settings.api_auth_enabled else "FAIL",
            severity="INFO" if settings.api_auth_enabled else "CRITICAL",
            description="/api 默认必须要求管理员身份，避免后台裸露。",
            evidence="API_AUTH_ENABLED=true" if settings.api_auth_enabled else "API_AUTH_ENABLED=false",
            action="" if settings.api_auth_enabled else "开启 API_AUTH_ENABLED=true。",
        )
    )

    database_password_weak = _database_password_is_weak(settings.database_url)
    production_env = settings.app_env in {"production", "prod"}
    if database_password_weak and production_env:
        database_status, database_severity = "FAIL", "HIGH"
        database_evidence = "生产环境检测到默认、缺失或过短的数据库密码"
        database_action = "设置至少 16 位随机 MYSQL_ROOT_PASSWORD / MYSQL_PASSWORD，并重新部署。"
    elif database_password_weak:
        database_status, database_severity = "PASS", "INFO"
        database_evidence = "当前为开发环境；生产 Compose 已强制要求独立数据库密码"
        database_action = ""
    else:
        database_status, database_severity = "PASS", "INFO"
        database_evidence = "数据库连接使用非默认密码"
        database_action = ""
    items.append(
        _item(
            category=category,
            code="database_password_strength",
            title="数据库凭据强度",
            status=database_status,
            severity=database_severity,
            description="生产数据库不能使用示例密码或空密码。",
            evidence=database_evidence,
            action=database_action,
        )
    )

    token_weak = _is_weak_secret(settings.admin_token, _DEFAULT_ADMIN_TOKENS, min_len=24)
    items.append(
        _item(
            category=category,
            code="admin_token_strength",
            title="后端管理凭据强度",
            status="FAIL" if token_weak else "PASS",
            severity="HIGH" if token_weak else "INFO",
            description="ADMIN_TOKEN 只在后端使用，上线必须是强随机值。",
            evidence="检测到默认或过短 ADMIN_TOKEN" if token_weak else "已配置非默认 ADMIN_TOKEN",
            action="在服务器环境变量中设置 32 位以上随机 ADMIN_TOKEN。" if token_weak else "",
        )
    )

    password_bcrypt_configured = bool(settings.admin_password_bcrypt)
    password_sha256_configured = bool(settings.admin_password_sha256)
    password_default = str(settings.admin_password or "").strip().lower() in _DEFAULT_PASSWORDS
    # P0-7: 优先 bcrypt，SHA256 作为兼容过渡，明文已移除
    password_weak = (not password_bcrypt_configured) and (password_default or password_sha256_configured or len(str(settings.admin_password or "")) < 12)
    if password_bcrypt_configured:
        password_evidence = "已配置 ADMIN_PASSWORD_BCRYPT（bcrypt 哈希）"
    elif password_sha256_configured:
        password_evidence = "已配置 ADMIN_PASSWORD_SHA256（已弃用，建议迁移到 ADMIN_PASSWORD_BCRYPT）"
    elif password_default:
        password_evidence = "检测到默认或过短密码"
    else:
        password_evidence = "未检测到密码配置"
    items.append(
        _item(
            category=category,
            code="admin_password_strength",
            title="管理员密码强度",
            status="PASS" if password_bcrypt_configured else ("FAIL" if password_weak else "WARN"),
            severity="INFO" if password_bcrypt_configured else ("HIGH" if password_weak else "MEDIUM"),
            description="前端只保留密码登录，密码必须使用 bcrypt 哈希存储，不支持明文。",
            evidence=password_evidence,
            action="使用 scripts/hash_password.py 生成 bcrypt 哈希并设置 ADMIN_PASSWORD_BCRYPT。" if not password_bcrypt_configured else "",
        )
    )

    app_secret_weak = _is_weak_secret(settings.app_secret_key, _DEFAULT_APP_SECRETS, min_len=32)
    same_as_token = bool(settings.app_secret_key and settings.admin_token and settings.app_secret_key == settings.admin_token)
    items.append(
        _item(
            category=category,
            code="app_secret_key_strength",
            title="服务端加密密钥",
            status="FAIL" if app_secret_weak or same_as_token else "PASS",
            severity="HIGH" if app_secret_weak or same_as_token else "INFO",
            description="APP_SECRET_KEY 用于模型 Key 等敏感字段加密，不能和开发 token 共用。",
            evidence="检测到默认/过短/与 ADMIN_TOKEN 相同的 APP_SECRET_KEY" if app_secret_weak or same_as_token else "APP_SECRET_KEY 已独立配置",
            action="设置 32 位以上随机 APP_SECRET_KEY，并与 ADMIN_TOKEN 分离。" if app_secret_weak or same_as_token else "",
        )
    )

    origins = list(settings.cors_origins)
    has_wildcard = any(origin.strip() == "*" for origin in origins)
    localhost_only = bool(origins) and all(_is_local_origin(origin) for origin in origins)
    if has_wildcard:
        cors_status, cors_severity = "FAIL", "HIGH"
        cors_evidence, cors_action = "CORS_ORIGINS 包含 *", "改成明确的前端域名白名单。"
    elif localhost_only:
        cors_status, cors_severity = "WARN", "LOW"
        cors_evidence, cors_action = f"当前仅配置本地源 {len(origins)} 个", "上线时补充正式前端域名。"
    else:
        cors_status, cors_severity = "PASS", "INFO"
        cors_evidence, cors_action = f"已配置 {len(origins)} 个 CORS origin", ""
    items.append(
        _item(
            category=category,
            code="cors_origins",
            title="CORS 白名单",
            status=cors_status,
            severity=cors_severity,
            description="跨域白名单应精确到正式前端域名，不能用通配符。",
            evidence=cors_evidence,
            action=cors_action,
        )
    )

    items.append(
        _item(
            category=category,
            code="rate_limit_enabled",
            title="基础限流",
            status="PASS" if settings.rate_limit_enabled else "WARN",
            severity="INFO" if settings.rate_limit_enabled else "MEDIUM",
            description="写操作和高频读取需要限流，避免误触生成、推送和实时探测。",
            evidence="RATE_LIMIT_ENABLED=true" if settings.rate_limit_enabled else "RATE_LIMIT_ENABLED=false",
            action="开启 RATE_LIMIT_ENABLED=true。" if not settings.rate_limit_enabled else "",
        )
    )

    lock_ok = settings.login_failure_limit <= 10 and settings.login_lock_seconds >= 60
    items.append(
        _item(
            category=category,
            code="login_lock_policy",
            title="登录失败锁定",
            status="PASS" if lock_ok else "WARN",
            severity="INFO" if lock_ok else "MEDIUM",
            description="密码登录需要失败次数限制和短期锁定（Redis 共享，多实例生效）。",
            evidence=f"失败阈值 {settings.login_failure_limit}，锁定 {settings.login_lock_seconds}s",
            action="建议 LOGIN_FAILURE_LIMIT<=10 且 LOGIN_LOCK_SECONDS>=60。" if not lock_ok else "",
        )
    )

    # P0-8: 生产环境应关闭自动文档
    docs_open = settings.docs_enabled
    items.append(
        _item(
            category=category,
            code="docs_endpoint_protection",
            title="API 文档端点保护",
            status="PASS" if not docs_open else "WARN",
            severity="INFO" if not docs_open else "MEDIUM",
            description="生产环境应关闭 /docs /redoc /openapi.json，避免 API 结构泄露。",
            evidence="DOCS_ENABLED=false（文档已关闭）" if not docs_open else "DOCS_ENABLED=true（文档公开）",
            action="设置 DOCS_ENABLED=false 关闭自动文档。" if docs_open else "",
        )
    )
    return items


def _build_data_items(db: Session, config: dict[str, Any], latest_run: AgentRun | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    category = "data_quality"
    briefing_cfg = config.get("briefing") if isinstance(config, dict) else {}
    briefing_cfg = briefing_cfg if isinstance(briefing_cfg, dict) else {}

    real_data_only = bool(briefing_cfg.get("real_data_only", True))
    evidence_policy = str(briefing_cfg.get("evidence_policy") or "").strip()
    strict_policy_ok = real_data_only and evidence_policy == "ITEM_LEVEL_HTTP_URL_REQUIRED"
    items.append(
        _item(
            category=category,
            code="strict_real_data_policy",
            title="真实数据策略",
            status="PASS" if strict_policy_ok else "FAIL",
            severity="INFO" if strict_policy_ok else "CRITICAL",
            description="情报系统必须禁止 sample/mock/fallback 进入 raw/event/briefing。",
            evidence=f"real_data_only={real_data_only}, evidence_policy={evidence_policy or '-'}",
            action="设置 real_data_only=true 且 evidence_policy=ITEM_LEVEL_HTTP_URL_REQUIRED。" if not strict_policy_ok else "",
        )
    )

    raw_rows = list(db.execute(select(HotspotRawItem).order_by(desc(HotspotRawItem.captured_at)).limit(500)).scalars())
    invalid_raw_count = sum(1 for row in raw_rows if not _raw_has_real_evidence(row))
    if not raw_rows:
        raw_status, raw_severity = "WARN", "MEDIUM"
        raw_evidence, raw_action = "暂无 raw_item 数据", "先执行一次早报生成或实时采集，确认真实来源入库。"
    elif invalid_raw_count:
        raw_status, raw_severity = "FAIL", "HIGH"
        raw_evidence = f"最近 {len(raw_rows)} 条 raw_item 中发现 {invalid_raw_count} 条无真实证据"
        raw_action = "清理历史无来源/样例数据，并重新生成情报。"
    else:
        raw_status, raw_severity = "PASS", "INFO"
        raw_evidence, raw_action = f"最近 {len(raw_rows)} 条 raw_item 均有 item 级 http(s) 来源", ""
    items.append(
        _item(
            category=category,
            code="raw_item_evidence",
            title="原始数据来源证据",
            status=raw_status,
            severity=raw_severity,
            description="进入数据库的原始条目必须有可点击原文链接。",
            evidence=raw_evidence,
            action=raw_action,
        )
    )

    event_rows = list(
        db.execute(
            select(HotspotEvent)
            .where(HotspotEvent.is_fallback_sample.is_(False))
            .order_by(desc(HotspotEvent.updated_at))
            .limit(200)
        ).scalars()
    )
    raw_ids: set[int] = set()
    event_to_raw: dict[str, list[int]] = {}
    for row in event_rows:
        ids = _safe_int_ids(row.raw_item_ids)
        event_to_raw[row.event_key] = ids
        raw_ids.update(ids[:20])
    valid_raw_ids: set[int] = set()
    if raw_ids:
        raw_for_events = db.execute(select(HotspotRawItem).where(HotspotRawItem.id.in_(list(raw_ids)))).scalars()
        valid_raw_ids = {row.id for row in raw_for_events if _raw_has_real_evidence(row)}
    event_without_evidence = sum(1 for row in event_rows if not (set(event_to_raw.get(row.event_key, [])) & valid_raw_ids))
    fallback_event_count = int(
        db.execute(select(func.count(HotspotEvent.id)).where(HotspotEvent.is_fallback_sample.is_(True))).scalar() or 0
    )
    if not event_rows:
        event_status, event_severity = "WARN", "MEDIUM"
        event_evidence, event_action = "暂无真实事件可验收", "执行一次异步早报生成，确认可产出真实情报事件。"
    elif event_without_evidence or fallback_event_count:
        event_status, event_severity = "FAIL", "HIGH"
        event_evidence = f"最近事件无证据 {event_without_evidence} 条，fallback 事件 {fallback_event_count} 条"
        event_action = "清理历史事件并重新跑生成任务，确保事件绑定 raw_item 证据。"
    else:
        event_status, event_severity = "PASS", "INFO"
        event_evidence, event_action = f"最近 {len(event_rows)} 条事件均可追溯到 raw_item 原文链接", ""
    items.append(
        _item(
            category=category,
            code="event_evidence_chain",
            title="事件级证据链",
            status=event_status,
            severity=event_severity,
            description="热点事件必须能追溯到至少一条真实 raw_item。",
            evidence=event_evidence,
            action=event_action,
        )
    )

    meta = latest_run.meta if latest_run and isinstance(latest_run.meta, dict) else {}
    data_quality = meta.get("data_quality") if isinstance(meta, dict) else {}
    data_quality = data_quality if isinstance(data_quality, dict) else {}
    dq_status = str(data_quality.get("status") or "")
    real_source_count = int(data_quality.get("real_source_count") or 0)
    real_item_count = int(data_quality.get("real_item_count") or 0)
    min_source_count = int(data_quality.get("minimum_real_source_count") or briefing_cfg.get("minimum_real_source_count") or 1)
    min_item_count = int(data_quality.get("minimum_real_item_count") or briefing_cfg.get("minimum_real_item_count") or 1)
    if latest_run is None:
        dq_ready, dq_severity = "WARN", "MEDIUM"
        dq_evidence, dq_action = "暂无 AgentRun", "上线前至少完成一次 SUCCESS 的异步生成任务。"
    elif dq_status == "PASS" or (real_source_count >= min_source_count and real_item_count >= min_item_count):
        dq_ready, dq_severity = "PASS", "INFO"
        dq_evidence, dq_action = f"最近任务真实来源 {real_source_count}/{min_source_count}，真实条目 {real_item_count}/{min_item_count}", ""
    else:
        dq_ready, dq_severity = "WARN", "HIGH"
        dq_evidence = f"最近任务数据质量 {dq_status or latest_run.status}，真实来源 {real_source_count}/{min_source_count}，真实条目 {real_item_count}/{min_item_count}"
        dq_action = "检查失败数据源或降低无证据数据比例后重新生成。"
    items.append(
        _item(
            category=category,
            code="latest_run_data_quality",
            title="最近任务数据覆盖",
            status=dq_ready,
            severity=dq_severity,
            description="最近一次 AgentRun 应达到真实来源数和真实条目数阈值。",
            evidence=dq_evidence,
            action=dq_action,
        )
    )

    latest_briefing_date = db.execute(select(func.max(DailyBriefing.briefing_date))).scalar_one_or_none()
    briefing = None
    if latest_briefing_date is not None:
        # 只取轻量字段，避免 markdown/raw_json 大字段参与排序触发 MySQL sort buffer 问题。
        briefing = (
            db.execute(
                select(DailyBriefing.briefing_date, DailyBriefing.status)
                .where(DailyBriefing.briefing_date == latest_briefing_date)
                .limit(1)
            )
            .mappings()
            .first()
        )
    if briefing is None:
        briefing_status, briefing_severity = "WARN", "MEDIUM"
        briefing_evidence, briefing_action = "暂无早报归档", "生成今日早报，确认 markdown 和来源证据可展示。"
    elif briefing["status"] != "SUCCESS":
        briefing_status, briefing_severity = "FAIL", "HIGH"
        briefing_evidence = f"最近早报 {briefing['briefing_date']} 状态 {briefing['status']}"
        briefing_action = "查看运行记录和系统日志，修复后重新生成。"
    else:
        briefing_status, briefing_severity = "PASS", "INFO"
        briefing_evidence, briefing_action = f"最近早报 {briefing['briefing_date']} 已成功归档", ""
    items.append(
        _item(
            category=category,
            code="briefing_archive",
            title="早报归档可用",
            status=briefing_status,
            severity=briefing_severity,
            description="可交付作品需要能产出并保留一份可复盘的情报早报。",
            evidence=briefing_evidence,
            action=briefing_action,
        )
    )
    return items


def _build_source_items(db: Session, config: dict[str, Any], latest_run: AgentRun | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    category = "sources"
    source_health = get_source_health_report(db, limit=50, live=False)
    enabled_sources = int(source_health.get("enabled_sources") or 0)
    healthy_sources = int(source_health.get("healthy_sources") or 0)
    degraded_sources = int(source_health.get("degraded_sources") or 0)
    down_sources = int(source_health.get("down_sources") or 0)
    avg_success_rate = float(source_health.get("avg_success_rate") or 0)

    configured_sources = _safe_list(config.get("sources") if isinstance(config, dict) else [])
    active_config_sources = [source for source in configured_sources if isinstance(source, dict) and source.get("enabled")]
    items.append(
        _item(
            category=category,
            code="enabled_source_count",
            title="启用数据源数量",
            status="PASS" if enabled_sources >= 3 else "FAIL" if enabled_sources == 0 else "WARN",
            severity="HIGH" if enabled_sources == 0 else "MEDIUM" if enabled_sources < 3 else "INFO",
            description="情报可信度依赖多个真实来源，不应只靠单一平台。",
            evidence=f"启用源 {enabled_sources} 个，配置启用 {len(active_config_sources)} 个",
            action="至少启用 3 个稳定公开源。" if enabled_sources < 3 else "",
        )
    )

    if enabled_sources == 0 or healthy_sources + degraded_sources == 0:
        coverage_status, coverage_severity = "FAIL", "HIGH"
    elif down_sources > max(1, enabled_sources // 2):
        coverage_status, coverage_severity = "WARN", "HIGH"
    else:
        coverage_status, coverage_severity = "PASS", "INFO"
    items.append(
        _item(
            category=category,
            code="source_health_coverage",
            title="采集源健康度",
            status=coverage_status,
            severity=coverage_severity,
            description="上线后需要知道哪些源可用、哪些源失败，失败不能伪装成成功。",
            evidence=f"健康 {healthy_sources}，降级 {degraded_sources}，不可用 {down_sources}，平均成功率 {avg_success_rate:.1f}%",
            action="打开数据源健康页实时探测失败源，并更新 connector 或关闭失效源。" if coverage_status != "PASS" else "",
        )
    )

    if latest_run is None:
        stale_status, stale_severity = "WARN", "MEDIUM"
        stale_evidence, stale_action = "暂无运行记录", "上线前至少跑通一次任务。"
    else:
        age = datetime.utcnow() - latest_run.started_at
        if latest_run.status in {"SUCCESS", "SKIPPED"} and age <= timedelta(hours=24):
            stale_status, stale_severity, stale_action = "PASS", "INFO", ""
        elif latest_run.status == "FAILED":
            stale_status, stale_severity, stale_action = "FAIL", "HIGH", "先修复最近失败任务，再进入交付验收。"
        elif age > timedelta(hours=24):
            stale_status, stale_severity, stale_action = "WARN", "MEDIUM", "最近任务已超过 24 小时，请重新触发并确认采集源仍可用。"
        else:
            stale_status, stale_severity, stale_action = "WARN", "MEDIUM", "确认任务没有卡在 RUNNING/QUEUED，必要时重新触发。"
        stale_evidence = f"最近任务 {latest_run.run_id}，状态 {latest_run.status}，开始于 {_iso(latest_run.started_at)}"
    items.append(
        _item(
            category=category,
            code="recent_run_freshness",
            title="最近采集任务新鲜度",
            status=stale_status,
            severity=stale_severity,
            description="上线验收不应依赖很久以前的旧数据。",
            evidence=stale_evidence,
            action=stale_action,
        )
    )
    return items


def _build_model_items(db: Session) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    category = "model_rag"
    providers = list(db.execute(select(AIModelProvider).order_by(AIModelProvider.priority.asc(), AIModelProvider.id.asc())).scalars())
    enabled = [provider for provider in providers if provider.enabled]
    configured_enabled = [provider for provider in enabled if (not provider.requires_api_key) or bool(provider.api_key) or bool(settings.ai_api_key)]

    items.append(
        _item(
            category=category,
            code="enabled_model_provider",
            title="模型供应商配置",
            status="PASS" if configured_enabled else "FAIL",
            severity="INFO" if configured_enabled else "HIGH",
            description="AI 分析链路至少需要一个可用的 OpenAI-compatible Provider 或明确的本地 Provider。",
            evidence=f"模型 Provider 总数 {len(providers)}，启用 {len(enabled)}，具备凭据/免凭据 {len(configured_enabled)}",
            action="在模型配置页启用至少一个 Provider，并完成连通性测试。" if not configured_enabled else "",
        )
    )

    tested_enabled = [provider for provider in enabled if provider.last_test_status]
    failed_tests = [provider for provider in enabled if provider.last_test_status == "FAILED"]
    success_tests = [provider for provider in enabled if provider.last_test_status == "SUCCESS"]
    if success_tests:
        test_status, test_severity = "PASS", "INFO"
        test_evidence, test_action = f"已有 {len(success_tests)} 个启用 Provider 最近测试成功", ""
    elif tested_enabled and len(failed_tests) == len(tested_enabled):
        test_status, test_severity = "FAIL", "HIGH"
        test_evidence, test_action = f"启用 Provider 中最近测试失败 {len(failed_tests)} 个", "修复模型 base_url/API key/model 后重新测试。"
    else:
        test_status, test_severity = "WARN", "MEDIUM"
        test_evidence, test_action = "启用 Provider 尚未完成连通性测试", "上线前在模型配置页执行一次测试。"
    items.append(
        _item(
            category=category,
            code="model_connectivity_test",
            title="模型连通性测试",
            status=test_status,
            severity=test_severity,
            description="正式演示前应验证模型能返回内容，避免现场降级到纯规则分析。",
            evidence=test_evidence,
            action=test_action,
        )
    )

    llm_stats = get_llm_stats(db, limit=10)
    recent_llm_rows = list(
        db.execute(select(LLMCallLog).where(LLMCallLog.created_at >= business_now_naive() - timedelta(hours=24))).scalars()
    )
    if recent_llm_rows:
        total_calls = len(recent_llm_rows)
        success_count = sum(1 for row in recent_llm_rows if row.status in {"SUCCESS", "CACHE_HIT"})
        failed_count = sum(1 for row in recent_llm_rows if row.status == "FAILED")
        success_rate = round(success_count / total_calls * 100, 1)
        stats_window = "24h"
    else:
        total_calls = int(llm_stats.get("total_calls") or 0)
        success_rate = float(llm_stats.get("success_rate") or 0)
        failed_count = int(llm_stats.get("failed_count") or 0)
        stats_window = "历史"
    if total_calls == 0:
        llm_status, llm_severity = "WARN", "LOW"
        llm_action, llm_evidence = "生成一次早报，观察 LLM 调用成功率和缓存命中。", "暂无 LLM 调用记录"
    elif success_rate < 80:
        llm_status, llm_severity = "WARN", "HIGH"
        llm_action = "检查模型 Provider、超时和错误日志。"
        llm_evidence = f"{stats_window} LLM 调用 {total_calls}，失败 {failed_count}，成功率 {success_rate:.1f}%"
    else:
        llm_status, llm_severity = "PASS", "INFO"
        llm_action = ""
        llm_evidence = f"{stats_window} LLM 调用 {total_calls}，失败 {failed_count}，成功率 {success_rate:.1f}%"
    items.append(
        _item(
            category=category,
            code="llm_runtime_success_rate",
            title="模型运行成功率",
            status=llm_status,
            severity=llm_severity,
            description="可观测的模型调用成功率能支撑上线后的排障。",
            evidence=llm_evidence,
            action=llm_action,
        )
    )

    qdrant_configured = bool(settings.qdrant_url and settings.qdrant_collection)
    embedding_remote = bool(settings.embedding_base_url and settings.embedding_api_key)
    items.append(
        _item(
            category=category,
            code="rag_embedding_config",
            title="RAG / Embedding 配置",
            status="PASS" if qdrant_configured else "WARN",
            severity="INFO" if qdrant_configured else "MEDIUM",
            description="知识库沉淀需要向量库集合和 embedding 策略。",
            evidence=(
                f"Qdrant collection 已配置；Embedding={'远程服务' if embedding_remote else '本地 Hashing 兜底'}"
                if qdrant_configured
                else "Qdrant URL 或 collection 未配置"
            ),
            action="配置 QDRANT_URL 和 QDRANT_COLLECTION。" if not qdrant_configured else "",
        )
    )
    return items


def _build_operations_items(db: Session) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    category = "operations"
    log_summary = get_log_summary(db)
    errors_24h = int(log_summary.get("errors_24h") or 0)
    warnings_24h = int(log_summary.get("warnings_24h") or 0)
    logs_total = int(log_summary.get("total") or 0)
    if errors_24h:
        log_status, log_severity, log_action = "FAIL", "HIGH", "进入系统日志页处理最近 24 小时 ERROR/CRITICAL。"
    elif warnings_24h > 10:
        log_status, log_severity, log_action = "WARN", "MEDIUM", "检查警告是否集中在同一模块。"
    else:
        log_status, log_severity, log_action = "PASS", "INFO", ""
    items.append(
        _item(
            category=category,
            code="system_logs_observability",
            title="系统日志可观测性",
            status=log_status,
            severity=log_severity,
            description="上线后需要能通过日志定位启动、任务、接口和人工操作问题。",
            evidence=f"日志总数 {logs_total}，24h 错误 {errors_24h}，24h 警告 {warnings_24h}",
            action=log_action,
        )
    )

    scheduler = load_scheduler_config(include_env=True)
    scheduler_enabled = bool(scheduler.get("enabled"))
    items.append(
        _item(
            category=category,
            code="scheduler_config",
            title="定时任务配置",
            status="PASS" if scheduler_enabled else "WARN",
            severity="INFO" if scheduler_enabled else "LOW",
            description="正式运行通常需要每天自动生成情报；演示环境可手动触发。",
            evidence=(
                f"已启用，每天 {scheduler.get('hour', '-')}:{str(scheduler.get('minute', '0')).zfill(2)} {scheduler.get('timezone', '')}"
                if scheduler_enabled
                else "调度未启用"
            ),
            action="如需无人值守，开启调度并确认下一次运行时间。" if not scheduler_enabled else "",
        )
    )

    push = load_push_config(include_env=True, mask_token=True)
    push_enabled = bool(push.get("enabled"))
    target_type = str(push.get("target_type") or "private")
    target_ok = bool(push.get("user_id")) if target_type == "private" else bool(push.get("group_id"))
    onebot_ok = bool(str(push.get("onebot_api_base") or "").strip())
    if not push_enabled:
        push_status, push_severity = "WARN", "LOW"
        push_evidence, push_action = "QQ / OneBot 推送未开启", "若交付要求自动触达，配置 QQ 机器人后开启推送。"
    elif not (target_ok and onebot_ok):
        push_status, push_severity = "FAIL", "HIGH"
        push_evidence = f"推送已开启但目标或 OneBot 地址不完整，target_type={target_type}"
        push_action = "补齐 onebot_api_base 与 user_id/group_id，并执行推送测试。"
    else:
        push_status, push_severity = "PASS", "INFO"
        push_evidence, push_action = f"推送已开启，target_type={target_type}，token 已脱敏", ""
    items.append(
        _item(
            category=category,
            code="push_delivery_config",
            title="推送通道配置",
            status=push_status,
            severity=push_severity,
            description="自动推送不是核心阻塞项，但交付演示要明确当前是否可触达。",
            evidence=push_evidence,
            action=push_action,
        )
    )

    migrations_dir = Path(PROJECT_ROOT / "migrations" / "versions")
    revisions = list(migrations_dir.glob("*.py")) if migrations_dir.exists() else []
    items.append(
        _item(
            category=category,
            code="alembic_revisions",
            title="数据库迁移脚手架",
            status="PASS" if revisions else "WARN",
            severity="INFO" if revisions else "MEDIUM",
            description="上线交付需要可追踪的数据库结构变更。",
            evidence=f"Alembic revision 数量 {len(revisions)}" if revisions else "未发现 Alembic revision",
            action="把轻量补列逐步迁入 Alembic revision。" if not revisions else "",
        )
    )

    scripts_ok = all(Path(PROJECT_ROOT / name).exists() for name in ("start.ps1", "stop.ps1", "check.ps1"))
    items.append(
        _item(
            category=category,
            code="ops_scripts",
            title="一键运维脚本",
            status="PASS" if scripts_ok else "WARN",
            severity="INFO" if scripts_ok else "MEDIUM",
            description="面试演示和交付验收需要稳定启动、停止和自检脚本。",
            evidence="start.ps1 / stop.ps1 / check.ps1 均存在" if scripts_ok else "启动/停止/自检脚本不完整",
            action="补齐 start.ps1、stop.ps1、check.ps1。" if not scripts_ok else "",
        )
    )
    return items


def _build_delivery_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    category = "delivery_assets"
    required_docs = [
        Path(PROJECT_ROOT / "README.md"),
        Path(PROJECT_ROOT / "docs" / "DELIVERY_CHECKLIST.md"),
        Path(PROJECT_ROOT / "docs" / "ARCHITECTURE.md"),
    ]
    missing_docs = [path.name for path in required_docs if not path.exists()]
    items.append(
        _item(
            category=category,
            code="delivery_docs",
            title="交付说明文档",
            status="PASS" if not missing_docs else "WARN",
            severity="INFO" if not missing_docs else "MEDIUM",
            description="项目需要能讲清楚定位、架构、启动和验收方式。",
            evidence="README / DELIVERY_CHECKLIST / ARCHITECTURE 均存在" if not missing_docs else f"缺少 {', '.join(missing_docs)}",
            action="补齐 README、架构说明和交付清单。" if missing_docs else "",
        )
    )

    removed_sample_ok = not Path(PROJECT_ROOT / "backend" / "app" / "connectors" / "sample.py").exists()
    reset_demo_ok = not Path(PROJECT_ROOT / "scripts" / "reset_demo_data.py").exists()
    fake_tools_ok = removed_sample_ok and reset_demo_ok
    items.append(
        _item(
            category=category,
            code="no_demo_data_tools",
            title="演示假数据入口清理",
            status="PASS" if fake_tools_ok else "FAIL",
            severity="INFO" if fake_tools_ok else "HIGH",
            description="用户已经明确不能接受假数据，交付包中不能保留一键造假入口。",
            evidence="未发现 sample connector / reset_demo_data.py" if fake_tools_ok else "仍存在 sample connector 或 demo reset 脚本",
            action="删除假数据 connector 和演示数据重置脚本。" if not fake_tools_ok else "",
        )
    )

    frontend_package = Path(PROJECT_ROOT / "frontend" / "package.json")
    backend_main = Path(PROJECT_ROOT / "backend" / "app" / "main.py")
    entries_ok = frontend_package.exists() and backend_main.exists()
    items.append(
        _item(
            category=category,
            code="frontend_backend_entrypoints",
            title="前后端入口完整",
            status="PASS" if entries_ok else "FAIL",
            severity="INFO" if entries_ok else "CRITICAL",
            description="交付态至少要具备可构建前端和可启动后端入口。",
            evidence="frontend/package.json 与 backend/app/main.py 均存在" if entries_ok else "前端或后端入口缺失",
            action="恢复缺失入口文件。" if not entries_ok else "",
        )
    )
    return items


def _sort_action_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actionable = [item for item in items if item["status"] in {"FAIL", "WARN"}]
    return sorted(
        actionable,
        key=lambda item: (
            0 if item["status"] == "FAIL" else 1,
            -_SEVERITY_RANK.get(item["severity"], 0),
            item["category"],
            item["code"],
        ),
    )


def get_deployment_readiness(db: Session) -> dict[str, Any]:
    """生成上线交付就绪报告。"""
    try:
        config = load_sources_config()
        config_error = ""
    except Exception as exc:  # noqa: BLE001
        config = {}
        config_error = str(exc)

    latest = _latest_run(db)
    latest_data_run = _latest_run(db, require_data=True)
    categories = [
        _category("security", "安全与访问控制", _build_security_items()),
        _category("data_quality", "真实数据与证据链", _build_data_items(db, config, latest_data_run)),
        _category("sources", "采集源健康", _build_source_items(db, config, latest_data_run)),
        _category("model_rag", "模型与知识库", _build_model_items(db)),
        _category("operations", "运维与自动化", _build_operations_items(db)),
        _category("delivery_assets", "交付资产", _build_delivery_items()),
    ]

    if config_error:
        categories.insert(
            0,
            _category(
                "config",
                "配置文件",
                [
                    _item(
                        category="config",
                        code="sources_config_load",
                        title="数据源配置读取",
                        status="FAIL",
                        severity="CRITICAL",
                        description="无法读取数据源配置会导致采集、推送和知识库策略不可控。",
                        evidence=config_error[:300],
                        action="修复 HOTSPOT_SOURCES_CONFIG 或 config/sources.example.yml。",
                    )
                ],
            ),
        )

    all_items = [item for category in categories for item in category["items"]]
    blockers = sum(1 for item in all_items if item["status"] == "FAIL")
    warnings = sum(1 for item in all_items if item["status"] == "WARN")
    passed = sum(1 for item in all_items if item["status"] == "PASS")
    total_penalty = sum(_PENALTY.get((item["status"], item["severity"]), 0) for item in all_items)
    readiness_score = round(max(0, min(100, 100 - total_penalty)), 1)
    has_critical = any(item["status"] == "FAIL" and item["severity"] == "CRITICAL" for item in all_items)

    if blockers or has_critical:
        readiness_level = "BLOCKED"
        production_ready = False
        summary = "存在上线阻塞项，先修复红色检查项。"
    elif readiness_score >= 85 and warnings <= 3:
        readiness_level = "READY"
        production_ready = True
        summary = "核心链路已满足交付要求，可进入部署验收。"
    else:
        readiness_level = "NEEDS_ATTENTION"
        production_ready = False
        summary = "主流程可演示，但仍有若干上线前风险需要确认。"

    return {
        "generated_at": utc_now_iso(),
        "readiness_score": readiness_score,
        "readiness_level": readiness_level,
        "production_ready": production_ready,
        "summary": summary,
        "passed": passed,
        "warnings": warnings,
        "blockers": blockers,
        "total_items": len(all_items),
        "top_actions": _sort_action_items(all_items)[:8],
        "categories": categories,
        "latest_run": {
            "run_id": latest_data_run.run_id if latest_data_run else latest.run_id if latest else None,
            "status": latest_data_run.status if latest_data_run else latest.status if latest else None,
            "started_at": _iso(latest_data_run.started_at) if latest_data_run else _iso(latest.started_at) if latest else None,
            "finished_at": _iso(latest_data_run.finished_at) if latest_data_run else _iso(latest.finished_at) if latest else None,
            "total_raw": latest_data_run.total_raw if latest_data_run else latest.total_raw if latest else 0,
            "total_events": latest_data_run.total_events if latest_data_run else latest.total_events if latest else 0,
            "is_data_run": bool(latest_data_run),
        },
        "config_summary": {
            "api_auth_enabled": settings.api_auth_enabled,
            "rate_limit_enabled": settings.rate_limit_enabled,
            "cors_origin_count": len(settings.cors_origins),
            "admin_token_configured": _env_present("ADMIN_TOKEN"),
            "admin_password_hash_configured": bool(
                settings.admin_password_bcrypt or settings.admin_password_sha256
            ),
            "app_secret_configured": _env_present("APP_SECRET_KEY"),
            "database_uses_default_local_password": _database_password_is_weak(settings.database_url),
            "sources_config_path": str(settings.sources_config_path),
        },
    }
