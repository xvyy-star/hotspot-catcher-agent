from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import AIModelProvider, LLMCallLog
from app.pipeline.langchain_analysis import LangChainHotspotAnalyzer
from app.services.llm_observability_service import get_llm_stats, log_llm_call
from app.services.model_provider_service import ModelProviderPayload, provider_to_dict


class _CapturingSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, row: object) -> None:
        self.added.append(row)


def _provider(**overrides: object) -> AIModelProvider:
    values = {
        "code": "priced-model",
        "name": "Priced model",
        "base_url": "http://models.test/v1",
        "model": "priced-v1",
        "requires_api_key": False,
        "input_cost_per_million": Decimal("2.50"),
        "output_cost_per_million": Decimal("10.00"),
    }
    values.update(overrides)
    return AIModelProvider(**values)


def test_provider_prices_default_to_zero_and_reject_negative_values() -> None:
    payload = ModelProviderPayload(
        code="free-model",
        name="Free model",
        base_url="http://models.test/v1",
        model="free-v1",
    )
    assert payload.input_cost_per_million == Decimal("0")
    assert payload.output_cost_per_million == Decimal("0")

    for field_name in ("input_cost_per_million", "output_cost_per_million"):
        with pytest.raises(ValidationError):
            ModelProviderPayload(
                code="invalid-price",
                name="Invalid price",
                base_url="http://models.test/v1",
                model="invalid-v1",
                **{field_name: "-0.01"},
            )


def test_provider_serialization_exposes_usd_prices_as_json_numbers() -> None:
    data = provider_to_dict(_provider())
    assert data["input_cost_per_million"] == 2.5
    assert data["output_cost_per_million"] == 10.0


def test_log_llm_call_freezes_cost_using_price_at_call_time() -> None:
    session = _CapturingSession()
    provider = _provider()
    event = SimpleNamespace(event_key="event-1", title="Cost tracking")

    log_llm_call(
        session,  # type: ignore[arg-type]
        run_id="run-1",
        event=event,  # type: ignore[arg-type]
        provider=provider,
        status="SUCCESS",
        latency_ms=120,
        usage={"input_tokens": "1000", "output_tokens": 500},
    )

    row = session.added[0]
    assert isinstance(row, LLMCallLog)
    assert row.prompt_tokens == 1000
    assert row.completion_tokens == 500
    assert row.total_tokens == 1500
    assert row.estimated_cost == Decimal("0.0075000000")

    provider.input_cost_per_million = Decimal("999")
    provider.output_cost_per_million = Decimal("999")
    assert row.estimated_cost == Decimal("0.0075000000")


def test_stats_sum_frozen_cost_globally_and_per_provider() -> None:
    created_at = datetime(2026, 7, 16, 1, 0)
    rows = [
        LLMCallLog(
            id=1,
            provider_code="provider-a",
            provider_name="Provider A",
            model="model-a",
            status="SUCCESS",
            cache_hit=False,
            latency_ms=100,
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            estimated_cost=Decimal("0.0075000000"),
            created_at=created_at,
        ),
        LLMCallLog(
            id=2,
            provider_code="provider-a",
            provider_name="Provider A",
            model="model-a",
            status="CACHE_HIT",
            cache_hit=True,
            latency_ms=2,
            total_tokens=0,
            estimated_cost=Decimal("0"),
            created_at=created_at,
        ),
        LLMCallLog(
            id=3,
            provider_code="provider-b",
            provider_name="Provider B",
            model="model-b",
            status="FAILED",
            cache_hit=False,
            latency_ms=300,
            prompt_tokens=2000,
            completion_tokens=0,
            total_tokens=2000,
            estimated_cost=Decimal("0.1000000000"),
            created_at=created_at,
        ),
    ]

    engine = create_engine("sqlite+pysqlite:///:memory:")
    LLMCallLog.__table__.create(engine)
    with Session(engine) as session:
        session.add_all(rows)
        session.commit()
        stats = get_llm_stats(session, limit=10)

    assert stats["total_estimated_cost"] == 0.1075
    provider_costs = {
        item["provider_code"]: item["total_estimated_cost"] for item in stats["provider_stats"]
    }
    assert provider_costs == {"provider-a": 0.0075, "provider-b": 0.1}
    assert stats["recent_calls"][0]["estimated_cost"] == 0.1


def test_openai_compatible_call_captures_response_usage(monkeypatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": '{"summary":"ok"}'}}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 8, "total_tokens": 50},
            }

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: Response())
    analyzer = LangChainHotspotAnalyzer(provider=_provider())
    prompt_value = SimpleNamespace(
        to_messages=lambda: [SimpleNamespace(type="human", content="hello")]
    )

    content = analyzer._call_openai_compatible(prompt_value)

    assert content == '{"summary":"ok"}'
    assert analyzer.last_usage == {
        "prompt_tokens": 42,
        "completion_tokens": 8,
        "total_tokens": 50,
    }
