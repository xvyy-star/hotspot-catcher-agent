"""LangChain 1.x 热点分析链。

这个模块的目标不是“为了用 LangChain 而用”，而是把热点分析流程明确拆成：
Prompt 构造 -> LLM 调用 -> JSON 解析 -> Schema 校验。

这样架构上可以讲清楚：
- LangChain 负责把分析链路标准化。
- 外部模型失败时仍然回到规则兜底。
- 输出必须结构化，不能直接相信模型自由文本。
"""
from __future__ import annotations

import json
import logging
from typing import Any

import requests
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field

from app.core.config import settings
from app.db.models import AIModelProvider
from app.schemas import HotspotEventDTO
from app.services.model_provider_service import provider_api_key

logger = logging.getLogger(__name__)


class HotspotAnalysisResult(BaseModel):
    """LLM 结构化输出 Schema。

    Pydantic 校验的价值：
    LLM 输出是概率性的，但业务系统需要确定结构。
    校验失败时可以重试或降级，避免脏数据进入数据库。
    """

    summary: str = Field(default="", description="一句话摘要")
    category: str = Field(default="综合", description="热点分类")
    risk_level: str = Field(default="LOW", description="LOW/MEDIUM/HIGH")
    risk_reason: str = Field(default="", description="风险原因")
    main_opinions: list[str] = Field(default_factory=list, description="主流观点")
    opposing_opinions: list[str] = Field(default_factory=list, description="反方或质疑观点")
    content_suggestions: list[str] = Field(default_factory=list, description="运营选题建议")


class LangChainHotspotAnalyzer:
    """基于 LangChain Runnable 的热点分析器。"""

    def __init__(self, provider: AIModelProvider | None = None) -> None:
        self.provider = provider
        self.last_error: str | None = None
        self.last_usage: dict[str, Any] = {}
        self.parser = JsonOutputParser()
        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是企业级热点情报分析 Agent。你必须只输出严格 JSON，不要 Markdown，不要解释。",
                ),
                (
                    "human",
                    """
请分析下面热点，并输出 JSON。

业务关注行业：{target_industry}

热点数据：
{hotspot_json}

输出字段必须包含：
- summary: 一句话摘要
- category: 按内容主题选 AI / 大模型、计算机技术、开源技术、科技产品、财经商业、政策监管或综合。
  AI 模型、智能体与 AI 应用归 AI / 大模型；数据库、操作系统、网络、云计算、安全归计算机技术。
  仅以开源项目、框架或版本发布为主的内容归开源技术；不要因为来源是 GitHub、HN 或 DEV 就归为开源技术。
- risk_level: 只能是 LOW、MEDIUM、HIGH
- risk_reason: 风险原因
- main_opinions: 字符串数组，最多 3 条
- opposing_opinions: 字符串数组，最多 3 条
- content_suggestions: 字符串数组，最多 3 条

如果 hotspot_json 里包含 knowledge_references / historical_insights：
- 可以把它们作为背景材料参考。
- 不要编造引用中没有的信息。
- content_suggestions 里优先体现“历史相似热点、业务关联度、是否值得继续追踪”。
""",
                ),
            ]
        )
        self.chain = self.prompt | RunnableLambda(self._call_openai_compatible) | self.parser

    @staticmethod
    def available() -> bool:
        """判断是否具备调用 LLM 的条件。"""
        return bool(settings.ai_base_url and settings.ai_model and settings.ai_api_key and not settings.ai_api_key.startswith("dummy"))

    def provider_available(self) -> bool:
        if self.provider is None:
            return self.available()
        if not self.provider.enabled:
            self.last_error = "模型 Provider 已禁用"
            return False
        if self.provider.requires_api_key and not provider_api_key(self.provider):
            self.last_error = "模型 Provider 未配置 API Key"
            return False
        return True

    def _call_openai_compatible(self, prompt_value: Any) -> str:
        """调用 OpenAI-compatible Chat Completions。

        这里没有直接使用 langchain-openai，是为了减少依赖和兼容各种国产兼容端点。
        LangChain 在这里负责链式编排、Prompt 和 Parser。
        """
        messages = []
        for msg in prompt_value.to_messages():
            role = "user"
            if msg.type == "system":
                role = "system"
            elif msg.type == "ai":
                role = "assistant"
            messages.append({"role": role, "content": msg.content})

        base_url = self.provider.base_url if self.provider else settings.ai_base_url
        api_key = provider_api_key(self.provider) if self.provider else settings.ai_api_key
        model = self.provider.model if self.provider else settings.ai_model
        temperature = self.provider.temperature if self.provider else 0.2
        max_tokens = self.provider.max_tokens if self.provider else 800
        timeout_seconds = self.provider.timeout_seconds if self.provider else 60
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        resp = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                # 结构化热点分析不需要长篇大论，限制输出长度可以降低延迟和成本。
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
            timeout=timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        raw_usage = data.get("usage") if isinstance(data, dict) else None
        self.last_usage = raw_usage if isinstance(raw_usage, dict) else {}
        return data["choices"][0]["message"]["content"]

    def analyze(self, event: HotspotEventDTO, target_industry: str) -> HotspotAnalysisResult | None:
        """分析单条热点。

        返回 None 表示 LLM 链路失败，调用方应降级到规则分析。
        """
        self.last_error = None
        self.last_usage = {}
        if not self.provider_available():
            if not self.last_error:
                self.last_error = "AI_API_KEY 未配置"
            return None

        hotspot_payload = {
            "title": event.title,
            "sources": event.source_codes,
            "heat_score": event.heat_score,
            "texts": [item.content or item.title for item in event.items[:5]],
            "tags": [tag for item in event.items for tag in item.tags[:3]],
            "business_relevance": event.business_relevance,
            "business_relevance_reason": event.business_relevance_reason,
            "historical_insights": event.historical_insights[:3],
            "knowledge_references": [
                {
                    "document_title": ref.get("document_title"),
                    "source": ref.get("source"),
                    "score": ref.get("score"),
                    "preview": ref.get("preview"),
                }
                for ref in event.rag_references[:3]
            ],
        }
        try:
            raw = self.chain.invoke(
                {
                    "target_industry": target_industry,
                    "hotspot_json": json.dumps(hotspot_payload, ensure_ascii=False),
                }
            )
            result = HotspotAnalysisResult.model_validate(raw)
            risk = result.risk_level.upper().strip()
            result.risk_level = risk if risk in {"LOW", "MEDIUM", "HIGH"} else "LOW"
            result.main_opinions = result.main_opinions[:3]
            result.opposing_opinions = result.opposing_opinions[:3]
            result.content_suggestions = result.content_suggestions[:3]
            return result
        except Exception as exc:  # noqa: BLE001
            # 这里故意兜住所有 LLM 链路异常：
            # - 网络失败 / Key 错误 / 模型服务超时
            # - 模型没有按 JSON 输出，导致 JsonOutputParser 解析失败
            # - Pydantic Schema 校验失败
            # 企业级 Agent 的关键不是“永不失败”，而是失败后不能拖垮主任务。
            logger.warning("LangChain 热点分析失败，降级规则分析: %s", exc)
            self.last_error = str(exc)[:500]
            return None
