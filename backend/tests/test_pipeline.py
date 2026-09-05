"""Pipeline 核心环节单元测试。

P0-9: 这些测试不需要真实 MySQL/Redis/Qdrant，可在 CI 无外部依赖运行。
覆盖去重、评分、证据闸门、产品聚焦过滤等纯函数逻辑。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("API_AUTH_ENABLED", "true")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-for-unit-test-only")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

from app.pipeline.deduplicate import deduplicate_items  # noqa: E402
from app.pipeline.evidence import (  # noqa: E402
    FAKE_SOURCE_CODES,
    has_real_evidence,
    is_fallback_item,
    is_http_url,
    split_items_by_evidence,
)
from app.pipeline.relevance import event_matches_product_focus, filter_events_for_product_focus  # noqa: E402
from app.pipeline.scoring import score_events  # noqa: E402
from app.schemas import HotspotEventDTO, HotspotItem  # noqa: E402


# ---------------------------------------------------------------------------
# 证据闸门测试
# ---------------------------------------------------------------------------


class TestEvidenceGate:
    def test_sample_items_are_blocked(self) -> None:
        item = HotspotItem(
            source="sample",
            source_name="样例",
            title="样例热点",
            url="https://example.com",
            raw_payload={"is_fallback_sample": True},
        )
        assert is_fallback_item(item) is True
        accepted, dropped_fallback, dropped_no_evidence = split_items_by_evidence([item])
        assert accepted == []
        assert dropped_fallback == 1
        assert dropped_no_evidence == 0

    def test_items_without_url_are_blocked(self) -> None:
        item = HotspotItem(
            source="github",
            source_name="GitHub",
            title="真实来源但无链接",
            raw_payload={"real_source": True},
        )
        accepted, dropped_fallback, dropped_no_evidence = split_items_by_evidence([item])
        assert accepted == []
        assert dropped_fallback == 0
        assert dropped_no_evidence == 1

    def test_real_items_with_url_pass(self) -> None:
        item = HotspotItem(
            source="github",
            source_name="GitHub",
            title="openai/codex",
            url="https://github.com/openai/codex",
            raw_payload={"real_source": True},
        )
        accepted, dropped_fallback, dropped_no_evidence = split_items_by_evidence([item])
        assert len(accepted) == 1
        assert dropped_fallback == 0
        assert dropped_no_evidence == 0
        assert has_real_evidence(accepted[0]) is True

    def test_fake_source_codes_contains_expected_entries(self) -> None:
        assert "sample" in FAKE_SOURCE_CODES
        assert "demo" in FAKE_SOURCE_CODES
        assert "mock" in FAKE_SOURCE_CODES
        assert "fake" in FAKE_SOURCE_CODES

    def test_is_http_url_validates_protocols(self) -> None:
        assert is_http_url("https://example.com") is True
        assert is_http_url("http://example.com") is True
        assert is_http_url("ftp://example.com") is False
        assert is_http_url("not-a-url") is False
        assert is_http_url("") is False
        assert is_http_url(None) is False


# ---------------------------------------------------------------------------
# 去重测试
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_identical_titles_are_merged(self) -> None:
        items = [
            HotspotItem(source="baidu", source_name="百度", title="OpenAI 发布 GPT-5", url="https://baidu.com/1"),
            HotspotItem(source="toutiao", source_name="头条", title="OpenAI 发布 GPT-5", url="https://toutiao.com/1"),
        ]
        events = deduplicate_items(items)
        assert len(events) == 1
        assert events[0].source_count == 2

    def test_different_titles_are_kept(self) -> None:
        items = [
            HotspotItem(source="baidu", source_name="百度", title="OpenAI 发布 GPT-5", url="https://baidu.com/1"),
            HotspotItem(source="github", source_name="GitHub", title="openai/codex 开源", url="https://github.com/openai/codex"),
        ]
        events = deduplicate_items(items)
        assert len(events) == 2

    def test_empty_input_returns_empty(self) -> None:
        assert deduplicate_items([]) == []


# ---------------------------------------------------------------------------
# 评分测试
# ---------------------------------------------------------------------------


class TestScoring:
    def test_events_get_scored(self) -> None:
        """评分后所有事件 heat_score 应大于 0。"""
        item_a = HotspotItem(source="baidu", source_name="百度", title="OpenAI 发布 GPT-5", url="https://example.com/a")
        item_b1 = HotspotItem(source="github", source_name="GitHub", title="openai/codex 开源", url="https://github.com/openai/codex")
        event_a = HotspotEventDTO(
            event_key="a",
            title="OpenAI 发布 GPT-5",
            items=[item_a],
            source_codes=["baidu"],
            source_count=1,
        )
        event_b = HotspotEventDTO(
            event_key="b",
            title="openai/codex 开源",
            items=[item_b1],
            source_codes=["github"],
            source_count=1,
        )
        scored = score_events([event_a, event_b])
        assert len(scored) == 2
        for event in scored:
            assert event.heat_score > 0

    def test_empty_input_returns_empty(self) -> None:
        assert score_events([]) == []


# ---------------------------------------------------------------------------
# 产品聚焦过滤测试
# ---------------------------------------------------------------------------


def _make_event(key: str, title: str, source: str = "github") -> HotspotEventDTO:
    """构造一个带 items 的 HotspotEventDTO。"""
    return HotspotEventDTO(
        event_key=key,
        title=title,
        items=[HotspotItem(source=source, source_name=source, title=title, url=f"https://example.com/{key}")],
        source_codes=[source],
        source_count=1,
    )


class TestProductFocus:
    def test_ai_tech_event_passes(self) -> None:
        event = _make_event("ai", "OpenAI 发布新的 Agent 编程工具")
        assert event_matches_product_focus(event) is True

    def test_sports_event_blocked(self) -> None:
        event = _make_event("sports", "C罗点球破门，葡萄牙取胜", source="baidu")
        assert event_matches_product_focus(event) is False

    def test_entertainment_event_blocked(self) -> None:
        event = _make_event("ent", "某明星演唱会门票售罄", source="toutiao")
        assert event_matches_product_focus(event) is False

    def test_filter_removes_noise(self) -> None:
        events = [
            _make_event("ai", "OpenAI 发布 GPT-5"),
            _make_event("sports", "C罗点球破门", source="baidu"),
        ]
        filtered = filter_events_for_product_focus(events)
        assert len(filtered) == 1
        assert filtered[0].event_key == "ai"


# ---------------------------------------------------------------------------
# 端到端 pipeline 测试（纯函数，无外部依赖）
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    def test_full_pipeline_filters_and_dedupes(self) -> None:
        """模拟从采集到评分的完整纯函数链路。"""
        items = [
            # 真实 AI 热点（通过）
            HotspotItem(
                source="github",
                source_name="GitHub",
                title="openai/codex 开源",
                url="https://github.com/openai/codex",
                raw_payload={"real_source": True},
            ),
            # 重复标题（应被去重合并）
            HotspotItem(
                source="hackernews",
                source_name="Hacker News",
                title="openai/codex 开源",
                url="https://news.ycombinator.com/item?id=1",
                raw_payload={"real_source": True},
            ),
            # 样例数据（应被证据闸门拦截）
            HotspotItem(
                source="sample",
                source_name="样例",
                title="样例热点",
                url="https://example.com",
                raw_payload={"is_fallback_sample": True},
            ),
            # 无链接（应被证据闸门拦截）
            HotspotItem(
                source="baidu",
                source_name="百度",
                title="无链接热点",
                raw_payload={"real_source": True},
            ),
        ]

        # 1. 证据闸门
        accepted, dropped_fallback, dropped_no_evidence = split_items_by_evidence(items)
        assert len(accepted) == 2
        assert dropped_fallback == 1
        assert dropped_no_evidence == 1

        # 2. 去重
        events = deduplicate_items(accepted)
        assert len(events) == 1  # 两条 openai/codex 合并为一条
        assert events[0].source_count == 2

        # 3. 评分
        scored = score_events(events)
        assert len(scored) == 1
        assert scored[0].heat_score > 0

        # 4. 产品聚焦过滤
        filtered = filter_events_for_product_focus(scored)
        assert len(filtered) == 1
