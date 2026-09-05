"""
ORM 数据模型。

设计原则：
1. raw_item 保存平台原始数据，方便追溯问题。
2. event 保存跨平台合并后的热点事件，服务业务展示。
3. briefing 保存每日早报，保证历史可查。
4. run 保存每次 Agent 执行记录，方便排查任务失败。
"""
from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class HotspotSource(Base):
    __tablename__ = "hotspot_source"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    strategy: Mapped[str | None] = mapped_column(String(80), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class HotspotRawItem(Base):
    __tablename__ = "hotspot_raw_item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_item_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_hot_score: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    raw_payload: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class HotspotEvent(Base):
    __tablename__ = "hotspot_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    heat_score: Mapped[float] = mapped_column(Float, nullable=False, default=0, index=True)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="LOW", index=True)
    risk_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    main_opinions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    opposing_opinions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    content_suggestions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    rag_references: Mapped[list | None] = mapped_column(JSON, nullable=True)
    historical_insights: Mapped[list | None] = mapped_column(JSON, nullable=True)
    knowledge_relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    knowledge_relevance_level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    business_relevance: Mapped[str | None] = mapped_column(String(30), nullable=True)
    business_relevance_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_mode: Mapped[str | None] = mapped_column(String(30), nullable=True)
    analysis_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    analysis_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    analysis_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    credibility_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    credibility_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    credibility_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_fallback_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    raw_item_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), index=True)


class HotspotEventFeedback(Base):
    """人工反馈。

    让产品从“只会生成情报”升级为“能被运营纠偏”：有用、无关、收藏、屏蔽都会回写数据库，
    后续排序、筛选和复盘都可以基于这张表形成闭环。
    """

    __tablename__ = "hotspot_event_feedback"
    __table_args__ = (
        UniqueConstraint("event_key", "action", "created_by", name="uq_hotspot_event_feedback_once"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(80), nullable=False, default="admin", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class DailyBriefing(Base):
    __tablename__ = "daily_briefing"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    briefing_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="SUCCESS")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AgentRun(Base):
    __tablename__ = "agent_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_raw: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class SystemLog(Base):
    """系统级运维日志。

    与 AgentRun 不同，SystemLog 记录跨模块的启动、配置、人工操作和异常事件，
    方便前端“系统日志”页直接排查问题。
    """

    __tablename__ = "system_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="INFO", index=True)
    module: Mapped[str] = mapped_column(String(80), nullable=False, default="system", index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    extra_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class AIModelProvider(Base):
    __tablename__ = "ai_model_provider"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    # 数据库中保存加密后的密钥；真实企业项目可进一步接 KMS / Vault / 云厂商 Secret Manager。
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    requires_api_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=800)
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)
    input_cost_per_million: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="USD per 1M input tokens",
    )
    output_cost_per_million: Mapped[Decimal] = mapped_column(
        Numeric(18, 8),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="USD per 1M output tokens",
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_test_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class DeletedModelProvider(Base):
    """用户主动删除过的模型通道 code。

    默认 Provider 只用于首次启动兜底；如果用户已经删过，后续启动不能再自动补回。
    """

    __tablename__ = "deleted_model_provider"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    deleted_by: Mapped[str] = mapped_column(String(80), nullable=False, default="admin")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class LLMAnalysisCache(Base):
    __tablename__ = "llm_analysis_cache"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    prompt_hash: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    event_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_industry: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_code: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    provider_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    result_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class LLMCallLog(Base):
    __tablename__ = "llm_call_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    event_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_code: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    provider_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    model: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="SUCCESS", index=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    cache_key: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 10),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="Frozen estimated call cost in USD",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class PushDeliveryLog(Base):
    __tablename__ = "push_delivery_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    briefing_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    target_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING", index=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    request_payload: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class KnowledgeDocument(Base):
    """知识库文档。

    MySQL 保存文档原文和元数据；向量库只保存 chunk 向量和检索 payload。
    """

    __tablename__ = "knowledge_document"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class KnowledgeChunk(Base):
    """知识库文本分块。

    chunk 原文保存在 MySQL，vector_id 对应 Qdrant points.id。
    """

    __tablename__ = "knowledge_chunk"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vector_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    embedding_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    embedding_dim: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class KnowledgeIngestRun(Base):
    """知识库导入运行记录。"""

    __tablename__ = "knowledge_ingest_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="RUNNING", index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    vector_collection: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

