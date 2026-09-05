"""知识问答 Query Router。

核心目标：
1. 不是所有输入都应该走 RAG。
2. 先判断用户输入属于寒暄、身份、帮助、澄清，还是知识库查询。
3. 只有知识密集型 / 明确资料查询型问题才触发向量检索。

这比“把所有问题都拿去检索”更符合业界常见的 Router / Adaptive RAG 思路。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoutedKnowledgeQuery:
    route: str
    intent: str
    latest_question: str
    normalized: str
    answer: str | None = None
    reason: str | None = None
    confidence: float = 1.0


class KnowledgeIntentRouter:
    """轻量确定性路由器。

    这里不用大模型做第一跳路由，原因是：
    - 避免“你好 / 吃饭了吗”这种输入也产生一次模型费用。
    - 避免模型服务超时时影响基础交互。
    - 对作品演示来说，可解释、稳定、可测试比炫技更重要。
    """

    DIRECT_GREETING = {
        "你好", "您好", "哈喽", "哈啰", "嗨", "在吗", "在不在",
        "早", "早上好", "上午好", "中午好", "下午好", "晚上好",
        "hi", "hello", "hey",
    }
    DIRECT_THANKS = {"谢谢", "谢谢你", "感谢", "感谢你", "多谢", "辛苦了", "thx", "thanks", "thankyou"}
    DIRECT_BYE = {"再见", "拜拜", "回头见", "先这样", "bye", "goodbye", "seeyou"}

    IDENTITY_PATTERNS = {
        "你是谁", "你到底是谁", "你叫什么", "你是啥", "你是什么",
        "你是干嘛的", "你是做什么的", "你是机器人吗", "你是ai吗",
        "介绍一下你", "自我介绍",
    }
    HELP_PATTERNS = {
        "帮助", "使用说明", "怎么用", "如何使用",
        "你能做什么", "能做什么", "你会什么", "怎么提问",
    }
    ASSISTANT_LIFE_PATTERNS = {
        "吃饭了吗", "吃饭没", "你吃饭了吗", "你吃了吗", "你喝水了吗",
        "你睡觉吗", "你睡了吗", "你累吗", "你开心吗", "你有感情吗",
        "你多大", "你几岁", "你在哪", "你在哪里", "你喜欢什么",
    }

    # 明确表示需要查库 / 查资料 / 做情报分析的触发词。
    RAG_TASK_TRIGGERS = {
        "知识库", "文档", "资料", "引用", "来源", "链接", "证据",
        "检索", "查询", "查一下", "搜索", "找一下",
        "总结", "概括", "归纳", "分析", "对比", "复盘", "提炼",
        "早报", "日报", "热点", "趋势", "风险", "可信度", "情报",
        "报告", "清单", "建议", "策略", "结论",
    }
    RAG_DOMAIN_TRIGGERS = {
        "ai", "agent", "llm", "rag", "openai", "github", "qdrant",
        "模型", "大模型", "智能体", "开源", "技术", "产品", "行业",
    }

    @classmethod
    def route(cls, question: str) -> RoutedKnowledgeQuery:
        latest = cls.extract_latest_question(question)
        normalized = cls.normalize(latest)
        if not normalized:
            return RoutedKnowledgeQuery(
                route="DIRECT_REPLY",
                intent="CLARIFY",
                latest_question=latest,
                normalized=normalized,
                answer="你可以直接问一个具体问题；如果是查资料、总结早报或分析热点，我会再检索知识库。",
                reason="empty_or_invalid",
            )

        direct = cls._direct_route(latest, normalized)
        if direct:
            return direct

        if cls._should_retrieve(latest, normalized):
            return RoutedKnowledgeQuery(
                route="RAG_QUERY",
                intent="KNOWLEDGE_QUERY",
                latest_question=latest,
                normalized=normalized,
                reason="explicit_knowledge_or_task_signal",
                confidence=0.9,
            )

        # 短句、口语句、没有明确知识任务的句子，不应该盲目查库。
        if len(normalized) <= 14:
            return RoutedKnowledgeQuery(
                route="DIRECT_REPLY",
                intent="SMALL_TALK_OR_CLARIFY",
                latest_question=latest,
                normalized=normalized,
                answer="这个问题不需要检索知识库。你如果想查资料，可以直接问具体内容，例如“总结 2026-07-06 早报里的 AI Agent 趋势”。",
                reason="short_without_knowledge_signal",
                confidence=0.75,
            )

        # 长句但没有知识信号时，先澄清，避免把无关问题硬塞给 RAG。
        return RoutedKnowledgeQuery(
            route="DIRECT_REPLY",
            intent="CLARIFY",
            latest_question=latest,
            normalized=normalized,
            answer="我主要负责知识库问答和热点情报分析。这个问题没有明确要查的资料范围，你可以补充文档、日期、热点名称或想分析的方向。",
            reason="no_knowledge_signal",
            confidence=0.65,
        )

    @classmethod
    def _direct_route(cls, latest: str, normalized: str) -> RoutedKnowledgeQuery | None:
        if normalized in cls.DIRECT_GREETING:
            return RoutedKnowledgeQuery(
                route="DIRECT_REPLY",
                intent="GREETING",
                latest_question=latest,
                normalized=normalized,
                answer="你好！我是热点捕手的知识问答助手。寒暄不会检索知识库；需要查资料时，请直接问具体问题。",
                reason="greeting",
            )
        if normalized in cls.DIRECT_THANKS:
            return RoutedKnowledgeQuery(
                route="DIRECT_REPLY",
                intent="THANKS",
                latest_question=latest,
                normalized=normalized,
                answer="不客气！需要查知识库时，直接问具体问题就行。",
                reason="thanks",
            )
        if normalized in cls.DIRECT_BYE:
            return RoutedKnowledgeQuery(
                route="DIRECT_REPLY",
                intent="BYE",
                latest_question=latest,
                normalized=normalized,
                answer="好的，后面需要继续分析热点或查询知识库时再叫我。",
                reason="bye",
            )
        if cls._contains_any(normalized, cls.IDENTITY_PATTERNS):
            return RoutedKnowledgeQuery(
                route="DIRECT_REPLY",
                intent="IDENTITY",
                latest_question=latest,
                normalized=normalized,
                answer="我是热点捕手的知识问答助手，负责回答知识库和热点情报相关问题。身份、寒暄这类问题我会直接回复，不检索知识库。",
                reason="assistant_identity",
            )
        if cls._contains_any(normalized, cls.HELP_PATTERNS):
            return RoutedKnowledgeQuery(
                route="DIRECT_REPLY",
                intent="HELP",
                latest_question=latest,
                normalized=normalized,
                answer="我可以做三件事：1）普通寒暄直接回复；2）你问具体资料、早报、热点、趋势时检索知识库；3）给出带引用的摘要和分析。你也可以勾选上方文档限定检索范围。",
                reason="help",
            )
        if cls._contains_any(normalized, cls.ASSISTANT_LIFE_PATTERNS):
            return RoutedKnowledgeQuery(
                route="DIRECT_REPLY",
                intent="ASSISTANT_LIFE",
                latest_question=latest,
                normalized=normalized,
                answer="我没有真实的生活状态，也不会吃饭或休息。我主要负责帮你查询知识库、总结早报和分析热点情报。",
                reason="assistant_life_smalltalk",
            )
        return None

    @classmethod
    def _should_retrieve(cls, latest: str, normalized: str) -> bool:
        if cls._contains_any(normalized, cls.RAG_TASK_TRIGGERS):
            return True
        if cls._contains_any(normalized, cls.RAG_DOMAIN_TRIGGERS) and len(normalized) >= 4:
            return True
        # 日期、编号、英文技术词组合通常是明确资料查询。
        if any(ch.isdigit() for ch in normalized) and cls._contains_any(normalized, {"早报", "日报", "热点", "趋势", "报告"}):
            return True
        if any(token in latest for token in ("#", "http://", "https://", "github.com", "arxiv")):
            return True
        return False

    @staticmethod
    def extract_latest_question(question: str) -> str:
        text = (question or "").strip()
        for marker in ("用户新问题：", "用户新问题:", "新问题：", "新问题:"):
            if marker in text:
                return text.rsplit(marker, 1)[-1].strip()
        return text

    @staticmethod
    def normalize(text: str) -> str:
        lowered = (text or "").strip().lower()
        punctuation = set(" \t\r\n,.;:!?~()[]{}<>\"'`_-")
        punctuation.update("，。！？～、；：（）【】《》“”‘’·…—")
        return "".join(ch for ch in lowered if ch not in punctuation)

    @staticmethod
    def _contains_any(text: str, patterns: set[str]) -> bool:
        return any(pattern in text for pattern in patterns)
