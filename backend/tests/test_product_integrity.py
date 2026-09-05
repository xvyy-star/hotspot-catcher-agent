from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest
import requests
from pydantic import ValidationError

from app.api import hotspots as hotspots_api
from app.services import (
    briefing_task_service,
    deployment_check_service,
    knowledge_file_parser,
    push_config_service,
    scheduler_service,
)
from app.services.model_provider_service import ModelProviderPayload, test_chat_completion as run_test_chat_completion
from app.services.push_config_service import PushConfigPayload
from app.services.push_service import _onebot_response_ok
from app.services.source_health_service import _judge_health_level
from app.services.source_health_service import REMOVED_SOURCE_CODES
from app.pipeline.evidence import FAKE_SOURCE_CODES


def test_all_briefing_entry_points_share_the_same_daily_lock() -> None:
    target_date = date(2026, 7, 14)
    assert briefing_task_service._slot_key(target_date) == scheduler_service.briefing_lock_key(target_date)


def test_scheduler_lock_fails_closed_when_redis_is_unavailable(monkeypatch) -> None:
    def broken_redis():
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(scheduler_service, "_redis_client", broken_redis)
    monkeypatch.setattr(scheduler_service, "settings", SimpleNamespace(scheduler_lock_fail_open=False))

    lock = scheduler_service.acquire_task_lock(date(2026, 7, 14), ttl_minutes=90)

    assert lock.acquired is False
    assert lock.backend == "redis-error"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"retcode": 0, "status": "ok"}, True),
        ({"retcode": 100, "status": "failed"}, False),
        ({"status": "failed", "wording": "denied"}, False),
        ({"data": {"user_id": 123}}, True),
        ({"message": "looks fine"}, False),
    ],
)
def test_onebot_response_requires_a_real_success_signal(body, expected: bool) -> None:
    ok, _ = _onebot_response_ok(body)
    assert ok is expected


def test_push_token_is_encrypted_at_rest(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "push.local.json"
    monkeypatch.setattr(push_config_service, "PUSH_LOCAL_CONFIG_PATH", config_path)
    secret = "unit-push-token-value"
    payload = PushConfigPayload(
        enabled=True,
        onebot_api_base="http://127.0.0.1:3000",
        target_type="private",
        user_id="123456",
        access_token=secret,
    )

    push_config_service.save_push_config(payload)

    assert secret not in config_path.read_text(encoding="utf-8")
    loaded = push_config_service.load_push_config(include_env=False, mask_token=False)
    assert loaded["access_token"] == secret


def test_push_connection_test_reuses_saved_token_when_form_leaves_it_blank(monkeypatch) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        hotspots_api,
        "load_push_config",
        lambda **_kwargs: {
            "onebot_api_base": "http://127.0.0.1:3000",
            "target_type": "private",
            "user_id": "123456",
            "access_token": "saved-token",
        },
    )

    def capture(cfg):
        captured.update(cfg)
        return {"ok": True}

    monkeypatch.setattr(hotspots_api, "test_onebot_connection", capture)
    result = hotspots_api.test_push_config(
        PushConfigPayload(
            onebot_api_base="http://127.0.0.1:3000",
            target_type="private",
            user_id="123456",
            access_token="",
        )
    )

    assert result["ok"] is True
    assert captured["access_token"] == "saved-token"


@pytest.mark.parametrize(
    "base_url",
    ["", "ftp://models.example/v1", "models.example/v1", "https://user:pass@models.example/v1"],
)
def test_model_provider_rejects_invalid_base_urls(base_url: str) -> None:
    with pytest.raises(ValidationError):
        ModelProviderPayload(code="unit-model", name="Unit", base_url=base_url, model="unit")


def test_model_connectivity_returns_structured_network_failure(monkeypatch) -> None:
    def broken_post(*args, **kwargs):
        del args, kwargs
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(requests, "post", broken_post)
    result = run_test_chat_completion("http://127.0.0.1:9/v1", "unit-model", timeout_seconds=5)

    assert result["ok"] is False
    assert result["status_code"] is None
    assert "连接失败" in result["message"]


def test_upload_validation_rejects_unsupported_and_oversized_files(monkeypatch) -> None:
    with pytest.raises(ValueError, match="暂不支持"):
        knowledge_file_parser.validate_knowledge_file_input("notes.exe", b"content")

    monkeypatch.setattr(knowledge_file_parser, "MAX_UPLOAD_BYTES", 4)
    with pytest.raises(ValueError, match="文件过大"):
        knowledge_file_parser.validate_knowledge_file_input("notes.txt", b"12345")


def test_stale_source_history_is_not_reported_as_healthy() -> None:
    item = {
        "enabled": True,
        "attempts": 5,
        "is_stale": True,
        "latest_status": "SUCCESS",
        "success_rate": 100,
        "availability_rate": 100,
    }
    assert _judge_health_level(item) == "STALE"


def test_fake_sources_are_excluded_from_health_aggregation() -> None:
    assert FAKE_SOURCE_CODES.issubset(REMOVED_SOURCE_CODES)


def test_operational_trends_align_run_model_token_and_push_quality() -> None:
    from app.services.system_metrics_service import _build_operational_trends

    first_day = datetime(2026, 7, 14, 9, 0)
    second_day = datetime(2026, 7, 15, 9, 0)
    trends = _build_operational_trends(
        ["2026-07-14", "2026-07-15"],
        runs=[
            SimpleNamespace(started_at=first_day, status="SUCCESS"),
            SimpleNamespace(started_at=first_day, status="FAILED"),
            SimpleNamespace(started_at=first_day, status="SKIPPED"),
            SimpleNamespace(started_at=second_day, status="SUCCESS"),
        ],
        llm_calls=[
            SimpleNamespace(created_at=first_day, status="SUCCESS", total_tokens=120, estimated_cost=0.005),
            SimpleNamespace(created_at=first_day, status="CACHE_HIT", total_tokens=0, estimated_cost=0),
            SimpleNamespace(created_at=first_day, status="FAILED", total_tokens=30, estimated_cost=0.0025),
        ],
        pushes=[
            SimpleNamespace(created_at=first_day, status="SUCCESS"),
            SimpleNamespace(created_at=first_day, status="FAILED"),
            SimpleNamespace(created_at=first_day, status="SKIPPED"),
        ],
    )

    assert trends[0] == {
        "date": "2026-07-14",
        "runs_total": 2,
        "runs_success": 1,
        "runs_failed": 1,
        "runs_skipped": 1,
        "run_success_rate": 50.0,
        "llm_calls": 3,
        "llm_success": 2,
        "llm_failed": 1,
        "llm_success_rate": 66.7,
        "llm_tokens": 150,
        "llm_cost": 0.0075,
        "push_total": 2,
        "push_success": 1,
        "push_failed": 1,
        "push_success_rate": 50.0,
    }
    assert trends[1]["run_success_rate"] == 100.0
    assert trends[1]["llm_calls"] == 0


def test_operational_trends_convert_utc_runs_to_business_day() -> None:
    from app.services.system_metrics_service import _build_operational_trends

    trends = _build_operational_trends(
        ["2026-07-15", "2026-07-16"],
        runs=[SimpleNamespace(started_at=datetime(2026, 7, 15, 16, 30), status="SUCCESS")],
        llm_calls=[],
        pushes=[],
    )

    assert trends[0]["runs_total"] == 0
    assert trends[1]["runs_total"] == 1


@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        ("mysql+pymysql://hotspot:hotspot123@mysql:3306/hotspot_agent", True),
        ("mysql+pymysql://hotspot:short@db.example:3306/hotspot_agent", True),
        ("mysql+pymysql://hotspot:strong-url-safe-password@mysql:3306/hotspot_agent", False),
    ],
)
def test_database_password_strength_parses_any_database_host(database_url: str, expected: bool) -> None:
    assert deployment_check_service._database_password_is_weak(database_url) is expected


def test_production_readiness_blocks_a_weak_database_password(monkeypatch) -> None:
    settings = SimpleNamespace(
        api_auth_enabled=True,
        admin_token="a" * 32,
        admin_password="",
        admin_password_bcrypt="bcrypt-configured",
        admin_password_sha256="",
        app_secret_key="b" * 40,
        cors_origins=("https://hotspot.example",),
        rate_limit_enabled=True,
        login_failure_limit=5,
        login_lock_seconds=300,
        docs_enabled=False,
        database_url="mysql+pymysql://hotspot:hotspot123@mysql:3306/hotspot_agent",
        app_env="production",
    )
    monkeypatch.setattr(deployment_check_service, "settings", settings)

    database_item = next(
        item
        for item in deployment_check_service._build_security_items()
        if item["code"] == "database_password_strength"
    )

    assert database_item["status"] == "FAIL"
    assert database_item["severity"] == "HIGH"
