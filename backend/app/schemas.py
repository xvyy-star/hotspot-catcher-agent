"""
Pydantic / 业务数据结构。

这些模型不是数据库表，而是 Agent 流水线内部传递的数据契约。
好处：采集器、清洗、去重、LLM 分析之间不直接依赖彼此实现。
"""
from __future__ import annotations

from datetime import datetime, date
from typing import Any, Literal
from pydantic import BaseModel, Field


class HotspotItem(BaseModel):
    """平台原始热点被转换后的统一结构。"""

    source: str
    source_name: str
    title: str
    url: str | None = None
    source_item_id: str | None = None
    rank: int | None = None
    raw_hot_score: str | None = None
    content: str | None = None
    tags: list[str] = Field(default_factory=list)
    captured_at: datetime = Field(default_factory=datetime.utcnow)
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class HotspotEventDTO(BaseModel):
    """去重合并后的热点事件。"""

    event_key: str
    title: str
    items: list[HotspotItem]
    source_codes: list[str]
    source_count: int
    heat_score: float = 0
    summary: str = ""
    category: str = "未分类"
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    risk_reason: str = ""
    main_opinions: list[str] = Field(default_factory=list)
    opposing_opinions: list[str] = Field(default_factory=list)
    content_suggestions: list[str] = Field(default_factory=list)
    # RAG 增强字段：
    # 在热点分析前检索知识库/历史早报，让 Agent 不只是“看当天热榜”，还能结合历史记忆。
    rag_references: list[dict[str, Any]] = Field(default_factory=list)
    historical_insights: list[str] = Field(default_factory=list)
    knowledge_relevance_score: float = 0
    knowledge_relevance_level: str = "NO_CONTEXT"
    business_relevance: str = "UNKNOWN"
    business_relevance_reason: str = ""
    # 分析来源可观测性：
    # LLM：真实模型分析；RULE：纯规则分析；RULE_FALLBACK：尝试 LLM 后失败，降级规则。
    analysis_mode: str = "RULE"
    analysis_model: str | None = None
    analysis_latency_ms: int | None = None
    analysis_error: str | None = None
    credibility_score: float = 0
    credibility_level: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"
    credibility_reason: str = ""
    is_fallback_sample: bool = False


class BriefingDTO(BaseModel):
    """今日早报结构。"""

    briefing_date: date
    title: str
    summary: str
    markdown: str
    events: list[HotspotEventDTO]
    status: str = "SUCCESS"
    source_health: dict[str, Any] = Field(default_factory=dict)


class GenerateBriefingResponse(BaseModel):
    run_id: str
    status: str
    briefing: BriefingDTO | None = None
    message: str = ""
