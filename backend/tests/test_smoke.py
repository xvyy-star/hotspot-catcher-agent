from __future__ import annotations

import os
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# P0-4: 测试环境配置 —— 需要设置 ADMIN_TOKEN 或 ADMIN_PASSWORD_BCRYPT 才能通过启动校验
os.environ.setdefault("API_AUTH_ENABLED", "true")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-for-unit-test-only")
os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.setdefault("AUTO_CREATE_TABLES", "true")
os.environ.setdefault("DOCS_ENABLED", "false")
# 使用 bcrypt 哈希的 test-admin-password
import bcrypt  # noqa: E402

_test_password_hash = bcrypt.hashpw(b"test-admin-password", bcrypt.gensalt(rounds=4)).decode("utf-8")
os.environ.setdefault("ADMIN_PASSWORD_BCRYPT", _test_password_hash)

from fastapi.testclient import TestClient  # noqa: E402

from app.core.secrets import encrypt_secret  # noqa: E402
from app.main import app  # noqa: E402
from app.services.model_provider_service import provider_to_dict  # noqa: E402
from app.services.system_log_service import write_system_log  # noqa: E402
from app.pipeline.evidence import has_real_evidence, split_items_by_evidence  # noqa: E402
from app.db.models import AIModelProvider, HotspotEvent  # noqa: E402
from app.db.session import SessionLocal, init_db, engine  # noqa: E402
from app.schemas import HotspotItem  # noqa: E402
from app.storage.repository import _event_matches_current_lane  # noqa: E402


if engine.url.get_backend_name() != "sqlite" or not Path(engine.url.database or "").parent.name.startswith("hotspot-pytest-"):
    raise RuntimeError("Smoke tests require the isolated conftest environment; do not use --noconftest")
init_db()
client = TestClient(app)


def auth_headers() -> dict[str, str]:
    """使用静态 ADMIN_TOKEN 进行服务间 API 调用（测试场景）。"""
    return {"Authorization": "Bearer test-admin-token", "X-Admin-Token": "test-admin-token"}


def test_health_and_system_status_are_public() -> None:
    assert client.get("/health").status_code == 200
    resp = client.get("/api/system/status")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["api_auth_enabled"] is True


def test_api_requires_admin_token() -> None:
    resp = client.get("/api/hotspots/events?limit=1")
    assert resp.status_code == 401


def test_api_accepts_admin_token() -> None:
    resp = client.get("/api/hotspots/events?limit=1", headers=auth_headers())
    assert resp.status_code == 200
    assert "data" in resp.json()


def test_login_issues_session_token_not_admin_token() -> None:
    """P0-1: 登录返回的 token 应该是会话 token，而非静态 ADMIN_TOKEN。"""
    bad = client.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    assert bad.status_code == 401

    password_login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "test-admin-password"},
    )
    assert password_login.status_code == 200
    data = password_login.json()["data"]
    assert data["profile"]["username"] == "admin"
    assert data["profile"]["auth_mode"] == "password"
    assert data["profile"]["auth_modes"] == ["password"]
    # P0-1: 返回的 token 不等于静态 ADMIN_TOKEN
    assert data["token"] != "test-admin-token"
    assert len(data["token"]) > 20
    assert data["expires_in"] > 0
    assert "login_security" in data["profile"]

    # 会话 token 可以访问受保护接口
    session_headers = {"Authorization": f"Bearer {data['token']}", "X-Admin-Token": data["token"]}
    me = client.get("/api/auth/me", headers=session_headers)
    assert me.status_code == 200
    me_data = me.json()["data"]
    assert me_data["username"] == "admin"
    assert me_data["auth_modes"] == ["password"]

    # P0-1: logout 后会话 token 失效
    logout = client.post("/api/auth/logout", headers=session_headers)
    assert logout.status_code == 200
    assert logout.json()["revoked"] is True

    # logout 后再用该 token 应 401
    after_logout = client.get("/api/auth/me", headers=session_headers)
    assert after_logout.status_code == 401


def test_login_failure_locks_account() -> None:
    """P0-2: 连续失败后应锁定。"""
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    locked = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert locked.status_code == 429


def test_system_logs_and_metrics_require_admin_token() -> None:
    assert client.get("/api/system/logs").status_code == 401
    assert client.get("/api/system/metrics").status_code == 401
    assert client.get("/api/system/readiness").status_code == 401

    logs = client.get("/api/system/logs?limit=5", headers=auth_headers())
    assert logs.status_code == 200
    assert isinstance(logs.json()["data"], list)

    metrics = client.get("/api/system/metrics", headers=auth_headers())
    assert metrics.status_code == 200
    data = metrics.json()["data"]
    assert "summary" in data
    assert "logs" in data
    assert len(data["trends"]["operations_7d"]) == 7
    assert "run_success_rate_7d" in data["summary"]
    assert "llm_tokens_24h" in data["summary"]
    assert "llm_cost_24h" in data["summary"]
    assert "feedback_positive_rate" in data["summary"]

    readiness = client.get("/api/system/readiness", headers=auth_headers())
    assert readiness.status_code == 200
    readiness_data = readiness.json()["data"]
    assert "readiness_score" in readiness_data
    assert "categories" in readiness_data
    assert "top_actions" in readiness_data
    assert any(item["code"] == "data_quality" for item in readiness_data["categories"])


def test_system_logs_can_delete_by_filter_or_all() -> None:
    with SessionLocal() as db:
        write_system_log(db, level="INFO", module="unit_delete", message="unit delete target alpha", commit=True)
        write_system_log(db, level="ERROR", module="unit_keep", message="unit keep target beta", commit=True)

    invalid_level = client.delete("/api/system/logs?level=NOPE&module=unit_delete", headers=auth_headers())
    assert invalid_level.status_code == 200
    assert invalid_level.json()["data"]["deleted_count"] == 0

    filtered = client.delete("/api/system/logs?module=unit_delete", headers=auth_headers())
    assert filtered.status_code == 200
    assert filtered.json()["data"]["deleted_count"] >= 1

    remaining = client.get("/api/system/logs?limit=50&keyword=unit", headers=auth_headers())
    assert remaining.status_code == 200
    messages = [item["message"] for item in remaining.json()["data"]]
    assert "unit delete target alpha" not in messages
    assert "unit keep target beta" in messages

    all_delete = client.delete("/api/system/logs?module=unit_keep", headers=auth_headers())
    assert all_delete.status_code == 200
    assert all_delete.json()["data"]["scope"] == "filtered"
    assert all_delete.json()["data"]["deleted_count"] >= 1

    empty = client.get("/api/system/logs?limit=5", headers=auth_headers())
    assert empty.status_code == 200

    with SessionLocal() as db:
        write_system_log(db, level="INFO", module="unit", message="unit log restored after delete test", commit=True)


def test_provider_to_dict_masks_secret() -> None:
    provider = AIModelProvider(
        code="unit",
        name="Unit Provider",
        base_url="http://unit.test/v1",
        api_key=encrypt_secret("sk-unit-secret"),
        model="unit-model",
    )
    data = provider_to_dict(provider)
    assert "api_key" not in data
    assert data["api_key_masked"].startswith("sk-")


def test_model_provider_delete_really_removes_row() -> None:
    code = "unit-delete-provider"
    with SessionLocal() as db:
        from sqlalchemy import delete

        from app.db.models import AIModelProvider, DeletedModelProvider

        db.execute(delete(AIModelProvider).where(AIModelProvider.code == code))
        db.execute(delete(DeletedModelProvider).where(DeletedModelProvider.code == code))
        db.commit()

    payload = {
        "code": code,
        "name": "Unit Delete Provider",
        "base_url": "http://127.0.0.1:18767/v1",
        "api_key": "",
        "model": "unit-model",
        "priority": 999,
        "enabled": False,
        "requires_api_key": False,
        "timeout_seconds": 60,
        "max_tokens": 800,
        "temperature": 0.2,
        "input_cost_per_million": 0.25,
        "output_cost_per_million": 1.5,
        "note": "unit delete smoke",
    }
    created = client.post("/api/models/providers", json=payload, headers=auth_headers())
    assert created.status_code == 200
    assert created.json()["data"]["input_cost_per_million"] == 0.25
    assert created.json()["data"]["output_cost_per_million"] == 1.5
    provider_id = created.json()["data"]["id"]

    duplicate = client.post("/api/models/providers", json=payload, headers=auth_headers())
    assert duplicate.status_code == 409

    changed_code_payload = {**payload, "code": f"{code}-renamed"}
    changed_code = client.put(
        f"/api/models/providers/{provider_id}",
        json=changed_code_payload,
        headers=auth_headers(),
    )
    assert changed_code.status_code == 409

    legacy_update_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"input_cost_per_million", "output_cost_per_million"}
    }
    legacy_update_payload["note"] = "legacy client update"
    legacy_update = client.put(
        f"/api/models/providers/{provider_id}",
        json=legacy_update_payload,
        headers=auth_headers(),
    )
    assert legacy_update.status_code == 200
    assert legacy_update.json()["data"]["input_cost_per_million"] == 0.25
    assert legacy_update.json()["data"]["output_cost_per_million"] == 1.5

    deleted = client.delete(f"/api/models/providers/{provider_id}", headers=auth_headers())
    assert deleted.status_code == 200
    assert deleted.json()["data"]["code"] == code

    listed = client.get("/api/models/providers", headers=auth_headers())
    assert listed.status_code == 200
    assert all(item["code"] != code for item in listed.json()["data"])

    with SessionLocal() as db:
        from sqlalchemy import delete

        from app.db.models import AIModelProvider, DeletedModelProvider

        db.execute(delete(AIModelProvider).where(AIModelProvider.code == code))
        db.execute(delete(DeletedModelProvider).where(DeletedModelProvider.code == code))
        db.execute(delete(DeletedModelProvider).where(DeletedModelProvider.code == f"{code}-renamed"))
        db.commit()


def test_knowledge_reindex_rejects_partial_collection_recreation() -> None:
    response = client.post(
        "/api/knowledge/reindex/async",
        headers=auth_headers(),
        json={"document_id": 1, "recreate_collection": True, "batch_size": 16},
    )
    assert response.status_code == 400
    assert "不能只选择单个文档" in response.json()["detail"]


def test_async_upload_rejects_unsupported_file_before_queueing() -> None:
    response = client.post(
        "/api/knowledge/documents/upload/async",
        headers=auth_headers(),
        files={"file": ("payload.exe", b"not a document", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "暂不支持" in response.json()["detail"]


def test_failed_knowledge_documents_are_excluded_from_all_search_paths() -> None:
    from sqlalchemy import delete, select

    from app.db.models import KnowledgeChunk, KnowledgeDocument
    from app.services.knowledge_service import KnowledgeService

    title = "Unit failed knowledge document"
    sentinel = "unit-failed-knowledge-sentinel"
    with SessionLocal() as db:
        old_ids = list(db.execute(select(KnowledgeDocument.id).where(KnowledgeDocument.title == title)).scalars())
        if old_ids:
            db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id.in_(old_ids)))
            db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id.in_(old_ids)))
            db.commit()

        doc = KnowledgeDocument(
            title=title,
            source="unit-test",
            content=sentinel,
            content_hash="unit-failed-hash",
            status="FAILED",
            error_message="unit failure",
        )
        db.add(doc)
        db.flush()
        chunk = KnowledgeChunk(
            document_id=doc.id,
            chunk_index=0,
            title=title,
            content=sentinel,
            content_hash="unit-failed-chunk-hash",
            token_count=len(sentinel),
        )
        db.add(chunk)
        db.commit()

        service = KnowledgeService()
        service.embedding_service.embed_query = lambda _query: [1.0]
        service.qdrant.search = lambda *_args, **_kwargs: [
            {"id": int(chunk.id), "score": 0.99, "payload": {"chunk_id": int(chunk.id)}}
        ]

        assert service.search(db, sentinel, top_k=5) == []

        db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
        db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id == doc.id))
        db.commit()


def test_low_coverage_briefing_counts_as_completed_for_duplicate_guard() -> None:
    from sqlalchemy import delete

    from app.db.models import DailyBriefing
    from app.services.scheduler_service import _existing_success_briefing

    target_date = date(2099, 1, 1)
    with SessionLocal() as db:
        db.execute(delete(DailyBriefing).where(DailyBriefing.briefing_date == target_date))
        db.add(
            DailyBriefing(
                briefing_date=target_date,
                title="Unit low coverage briefing",
                markdown="# Unit",
                status="LOW_REAL_COVERAGE",
            )
        )
        db.commit()

        assert _existing_success_briefing(db, target_date) is not None

        db.execute(delete(DailyBriefing).where(DailyBriefing.briefing_date == target_date))
        db.commit()


def test_event_lane_filters_old_noise() -> None:
    noisy = HotspotEvent(
        event_key="noise",
        title="C罗点球破门，葡萄牙取胜",
        category="AI / 大模型",
        heat_score=99,
        risk_level="LOW",
        source_codes=["baidu"],
        source_count=1,
        first_seen_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow(),
    )
    assert _event_matches_current_lane(noisy) is False

    tech = HotspotEvent(
        event_key="tech",
        title="OpenAI 发布新的 Agent 编程工具",
        category="AI / 大模型",
        heat_score=99,
        risk_level="LOW",
        source_codes=["baidu"],
        source_count=1,
        first_seen_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow(),
    )
    assert _event_matches_current_lane(tech) is False
    tech.source_codes = ["hackernews"]
    assert _event_matches_current_lane(tech) is True

    hackernews_noise = HotspotEvent(
        event_key="hn-noise",
        title="Airplane Boneyards List and Map",
        category="开源技术",
        heat_score=80,
        risk_level="LOW",
        source_codes=["hackernews"],
        source_count=1,
        first_seen_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow(),
    )
    assert _event_matches_current_lane(hackernews_noise) is False


def test_real_evidence_gate_blocks_samples_and_missing_urls() -> None:
    sample = HotspotItem(
        source="sample",
        source_name="样例数据",
        title="样例热点",
        raw_payload={"is_fallback_sample": True},
    )
    no_url = HotspotItem(
        source="github",
        source_name="GitHub Trending",
        title="真实来源但缺少原文链接",
        raw_payload={"real_source": True},
    )
    real = HotspotItem(
        source="github",
        source_name="GitHub Trending",
        title="openai/codex",
        url="https://github.com/openai/codex",
        raw_payload={"real_source": True},
    )

    accepted, dropped_fallback, dropped_no_evidence = split_items_by_evidence([sample, no_url, real])
    assert accepted == [real]
    assert dropped_fallback == 1
    assert dropped_no_evidence == 1
    assert has_real_evidence(real) is True
    assert real.raw_payload["has_real_evidence"] is True


def test_event_feedback_flow_requires_admin_and_updates_summary() -> None:
    event_key = "unit-feedback-event"
    missing_event_key = "unit-feedback-missing-event"
    with SessionLocal() as db:
        from sqlalchemy import delete

        from app.db.models import HotspotEventFeedback

        db.execute(delete(HotspotEventFeedback).where(HotspotEventFeedback.event_key == event_key))
        db.execute(delete(HotspotEventFeedback).where(HotspotEventFeedback.event_key == missing_event_key))
        db.execute(delete(HotspotEvent).where(HotspotEvent.event_key == event_key))
        db.execute(delete(HotspotEvent).where(HotspotEvent.event_key == missing_event_key))
        db.add(
            HotspotEvent(
                event_key=event_key,
                title="AI Agent 筛选测试情报",
                category="AI / 大模型",
                heat_score=88,
                risk_level="HIGH",
                source_count=2,
            )
        )
        db.commit()

    missing = client.post(
        f"/api/hotspots/events/{missing_event_key}/feedback",
        headers=auth_headers(),
        json={"action": "USEFUL"},
    )
    assert missing.status_code == 404

    assert client.post(f"/api/hotspots/events/{event_key}/feedback", json={"action": "USEFUL"}).status_code == 401

    created = client.post(
        f"/api/hotspots/events/{event_key}/feedback",
        headers=auth_headers(),
        json={"action": "USEFUL", "note": "unit positive"},
    )
    assert created.status_code == 200
    data = created.json()["data"]
    assert data["summary"]["counts"]["USEFUL"] >= 1
    assert data["summary"]["positive_count"] >= 1

    listed = client.get(f"/api/hotspots/events/{event_key}/feedback", headers=auth_headers())
    assert listed.status_code == 200
    assert any(item["action"] == "USEFUL" for item in listed.json()["data"])

    records = client.get(
        "/api/hotspots/feedback",
        headers=auth_headers(),
        params={
            "action": "USEFUL",
            "keyword": event_key,
            "category": "AI / 大模型",
            "risk_level": "HIGH",
        },
    )
    assert records.status_code == 200
    records_data = records.json()["data"]
    assert "items" in records_data
    assert "summary" in records_data
    assert any(item["event_key"] == event_key and item["action"] == "USEFUL" for item in records_data["items"])

    mismatch = client.get(
        "/api/hotspots/feedback",
        headers=auth_headers(),
        params={"keyword": event_key, "risk_level": "LOW"},
    )
    assert mismatch.status_code == 200
    assert not any(item["event_key"] == event_key for item in mismatch.json()["data"]["items"])

    invalid_risk = client.get(
        "/api/hotspots/feedback",
        headers=auth_headers(),
        params={"risk_level": "CRITICAL"},
    )
    assert invalid_risk.status_code == 400

    deleted = client.delete(f"/api/hotspots/events/{event_key}/feedback/USEFUL", headers=auth_headers())
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted_count"] >= 1

    with SessionLocal() as db:
        from sqlalchemy import delete

        db.execute(delete(HotspotEvent).where(HotspotEvent.event_key == event_key))
        db.commit()


def test_orphan_feedback_does_not_pollute_operator_metrics() -> None:
    from sqlalchemy import delete

    from app.db.models import HotspotEventFeedback
    from app.services.feedback_service import blocked_event_keys, get_feedback_overview, list_feedback_records

    event_key = "unit-orphan-feedback"
    with SessionLocal() as db:
        db.execute(delete(HotspotEventFeedback).where(HotspotEventFeedback.event_key == event_key))
        db.execute(delete(HotspotEvent).where(HotspotEvent.event_key == event_key))
        db.commit()
        before = get_feedback_overview(db)

        db.add(HotspotEventFeedback(event_key=event_key, action="BLOCK", created_by="admin"))
        db.commit()

        after = get_feedback_overview(db)
        assert after == before
        assert event_key not in blocked_event_keys(db)
        assert all(item["event_key"] != event_key for item in list_feedback_records(db, keyword=event_key))

        db.execute(delete(HotspotEventFeedback).where(HotspotEventFeedback.event_key == event_key))
        db.commit()


def test_run_detail_endpoint_returns_task_shape() -> None:
    run_id = "unit-run-detail"
    with SessionLocal() as db:
        from sqlalchemy import delete

        from app.db.models import AgentRun
        from app.storage.repository import create_run, finish_run

        db.execute(delete(AgentRun).where(AgentRun.run_id == run_id))
        db.commit()
        create_run(db, run_id, status="QUEUED", meta={"mode": "async", "progress": 8, "target_date": date.today().isoformat()})
        finish_run(db, run_id, "SKIPPED", meta={"mode": "async", "progress": 100, "target_date": date.today().isoformat()})
        db.commit()

    resp = client.get(f"/api/hotspots/runs/{run_id}", headers=auth_headers())
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["run_id"] == run_id
    assert data["progress"] == 100
    assert data["mode"] == "async"

    with SessionLocal() as db:
        from sqlalchemy import delete

        from app.db.models import AgentRun

        db.execute(delete(AgentRun).where(AgentRun.run_id == run_id))
        db.commit()
