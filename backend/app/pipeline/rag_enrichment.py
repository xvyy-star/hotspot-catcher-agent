"""热点分析阶段的 RAG 增强。

目标：
1. 在 LLM / 规则分析前，先用当前热点去检索知识库和历史早报。
2. 给事件补充“历史相似材料、业务关联度、引用来源”。
3. 让后续 LLM 分析可以基于这些引用做更稳的摘要和选题建议。

注意：
- 这里不强依赖 LLM，RAG 检索失败也不能影响今日早报生成。
- 第一版只做 Top N 热点的检索，避免每次生成早报都对 Qdrant 打太多请求。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.schemas import HotspotEventDTO
from app.services.knowledge_service import KnowledgeSearchResult, KnowledgeService

logger = logging.getLogger(__name__)


COMPUTER_KEYWORDS = {
    "ai",
    "agent",
    "llm",
    "openai",
    "deepseek",
    "github",
    "大模型",
    "智能体",
    "开源",
    "模型",
    "算力",
    "芯片",
    "编程",
    "程序员",
    "数据库",
    "框架",
    "算法",
    "论文",
    "鸿蒙",
}

POLICY_REFERENCE_KEYWORDS = {
    "中央",
    "军委",
    "政府",
    "国务院",
    "政策",
    "会议",
    "民生",
    "经济",
    "外交",
    "法治",
    "高质量发展",
    "乡村",
    "生态",
    "就业",
    "教育",
}

# 来源本身也能提供很强的业务信号：
# - GitHub / HN / arXiv / IT之家 默认偏 AI / 计算机行业。
# - 政策类 RSS 默认只作为监管/政策参考，不再进入主业务高相关判断。
# 后续可以替换为 LLM 结构化评分器。
COMPUTER_SOURCE_CODES = {"github", "hackernews", "arxiv_ai", "huggingface", "devto"}
POLICY_REFERENCE_SOURCE_CODES = set()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _build_rag_query(event: HotspotEventDTO, target_industry: str) -> str:
    """构造知识库检索问题。

    查询里混合标题、分类、来源和业务方向，能同时召回：
    - 历史早报中的相似热点。
    - 用户上传的行业资料 / 产品资料 / 技术资料。
    """
    item_texts = [item.content or item.title for item in event.items[:3]]
    query_parts = [
        event.title,
        event.summary,
        event.category,
        " ".join(event.source_codes),
        target_industry,
        *item_texts,
    ]
    return _normalize_text(" ".join(part for part in query_parts if part))[:1200]


def _reference_to_dict(item: KnowledgeSearchResult) -> dict[str, Any]:
    """把知识库检索结果压成适合写入早报 raw_json 的轻量引用。"""
    return {
        "document_id": item.document_id,
        "document_title": item.document_title,
        "chunk_id": item.chunk_id,
        "chunk_index": item.chunk_index,
        "score": round(float(item.score or 0), 4),
        "source": item.source,
        "preview": _normalize_text(item.content[:220]),
    }


def _event_feature_text(event: HotspotEventDTO) -> str:
    """提取用于业务相关性判断的事件自身特征。

    这里故意不放入 target_industry。
    原因：target_industry 是“项目想关注什么”，不是“热点本身是什么”。
    如果把“AI / 计算机行业 / 产品情报”拼进去，任何热点都会被误判为命中主线。
    """
    parts: list[str] = [
        event.title,
        event.summary,
        event.category,
        " ".join(event.source_codes or []),
        " ".join(event.main_opinions or []),
        " ".join(event.content_suggestions or []),
    ]

    for item in (event.items or [])[:5]:
        parts.extend(
            [
                item.source,
                item.source_name,
                item.title,
                item.content or "",
                " ".join(item.tags or []),
            ]
        )

        # 不同采集器 raw_payload 字段不统一，只取常见文本字段，避免把整段 JSON 塞进规则。
        raw_payload = item.raw_payload or {}
        for key in ("title", "name", "desc", "description", "summary", "content", "category", "tag", "tags", "keyword"):
            value = raw_payload.get(key)
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, list):
                parts.extend(str(v) for v in value[:8])

    return _normalize_text(" ".join(part for part in parts if part)).lower()[:5000]


def _keyword_hit(text: str, keywords: set[str]) -> bool:
    """判断关键词是否命中。

    中文关键词适合直接做子串匹配；英文短词不能直接 `in`。
    例如 `ai in baidu == True`，会把百度来源误判成 AI 技术热点，所以英文词用近似单词边界。
    """
    for keyword in keywords:
        key = keyword.lower().strip()
        if not key:
            continue
        if re.fullmatch(r"[a-z0-9_.+-]+", key):
            if re.search(rf"(?<![a-z0-9_.+-]){re.escape(key)}(?![a-z0-9_.+-])", text):
                return True
            continue
        if key in text:
            return True
    return False


def _infer_business_relevance(event: HotspotEventDTO, target_industry: str, references: list[dict[str, Any]]) -> tuple[str, str]:
    """粗略判断热点与项目定位的关联度。

    第一版先用规则可解释地判断“AI / 计算机行业 / 产品情报”相关性；
    后续可以把这一步升级成 LLM + RAG 结构化评分。
    """
    _ = target_industry  # 保留参数方便后续切到“用户自定义行业画像”，当前规则不直接拼接它，避免误判。

    source_codes = {str(code or "").lower() for code in (event.source_codes or [])}
    text = _event_feature_text(event)
    has_computer = bool(source_codes & COMPUTER_SOURCE_CODES) or _keyword_hit(text, COMPUTER_KEYWORDS)
    has_policy_reference = bool(source_codes & POLICY_REFERENCE_SOURCE_CODES) or _keyword_hit(text, POLICY_REFERENCE_KEYWORDS)
    has_reference = bool(references)
    has_history = any(str(ref.get("source") or "").startswith("daily_briefing") for ref in references)

    if has_computer:
        return "HIGH", "命中 AI / 计算机行业主线，适合用于技术趋势、产品判断或内容选题。"
    if has_policy_reference:
        return "MEDIUM", "命中政策/监管参考信息，可用于判断外部环境，但不是默认主线热点。"
    if has_history:
        return "MEDIUM", "知识库历史早报中存在相近材料，建议作为连续趋势观察。"
    if has_reference:
        return "MEDIUM", "知识库检索到可参考材料，但与当前两条主线的强相关性还需要人工确认。"
    return "LOW", "暂未检索到明确知识库依据，建议只作为普通综合热点观察。"


def _build_historical_insights(references: list[dict[str, Any]]) -> list[str]:
    if not references:
        return []

    top = references[0]
    insights = [
        f"知识库检索到 {len(references)} 条参考材料，最高相关来源为《{top.get('document_title')}》chunk#{top.get('chunk_index')}。"
    ]
    if any(str(ref.get("source") or "").startswith("daily_briefing") for ref in references):
        insights.append("历史早报中出现过相近主题，可作为连续热点或趋势复盘观察。")
    if any(not str(ref.get("source") or "").startswith("daily_briefing") for ref in references):
        insights.append("除历史早报外，还有知识库资料可补充背景，适合增强观点分析依据。")
    return insights[:3]


def _relevance_level(score: float, has_reference: bool) -> str:
    """给知识库召回结果一个可展示等级。

    不同 embedding 模型分数尺度不完全一致，因此这里把“是否召回到材料”和分数结合起来，
    避免本地 hashing embedding 分数偏低时直接误判为无关。
    """
    if not has_reference:
        return "NO_CONTEXT"
    if score >= 0.65:
        return "HIGH"
    if score >= 0.25:
        return "MEDIUM"
    return "LOW"


def enrich_event_with_rag(
    db: Session,
    event: HotspotEventDTO,
    *,
    target_industry: str,
    top_k: int = 3,
) -> HotspotEventDTO:
    """给单条热点补充 RAG 引用和业务关联判断。"""
    query = _build_rag_query(event, target_industry)
    if not query:
        return event

    rows = KnowledgeService().search(db, query, top_k=top_k)
    references = [_reference_to_dict(row) for row in rows]
    top_score = max((float(ref.get("score") or 0) for ref in references), default=0.0)

    event.rag_references = references
    event.knowledge_relevance_score = round(top_score, 4)
    event.knowledge_relevance_level = _relevance_level(top_score, bool(references))
    event.historical_insights = _build_historical_insights(references)
    event.business_relevance, event.business_relevance_reason = _infer_business_relevance(event, target_industry, references)
    return event


def enrich_events_with_rag(
    events: list[HotspotEventDTO],
    *,
    db: Session | None,
    target_industry: str,
    enabled: bool = True,
    limit: int = 10,
    top_k: int = 3,
) -> list[HotspotEventDTO]:
    """批量执行 RAG 增强。

    只处理前 limit 条热点，后面的事件保持原样，保证早报生成速度可控。
    """
    if not enabled or db is None or not events:
        return events

    enriched: list[HotspotEventDTO] = []
    safe_limit = max(0, min(int(limit or 0), len(events)))
    safe_top_k = max(1, min(int(top_k or 3), 10))
    for idx, event in enumerate(events):
        if idx >= safe_limit:
            enriched.append(event)
            continue
        try:
            enriched.append(
                enrich_event_with_rag(
                    db,
                    event,
                    target_industry=target_industry,
                    top_k=safe_top_k,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("热点 RAG 增强失败，跳过该事件 event=%s error=%s", event.title, exc)
            event.knowledge_relevance_level = "ERROR"
            event.business_relevance = "UNKNOWN"
            event.business_relevance_reason = f"知识库检索失败：{str(exc)[:200]}"
            enriched.append(event)
    return enriched
