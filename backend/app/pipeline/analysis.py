"""热点事件分析模块。

这个模块负责给去重后的热点事件补充：分类、摘要、观点、风险等级、选题建议。
优先使用 LangChain + LLM；模型不可用、超出 Top N 或调用失败时，回退到规则分析。
"""
from __future__ import annotations

import logging
import time

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AIModelProvider
from app.pipeline.langchain_analysis import HotspotAnalysisResult, LangChainHotspotAnalyzer
from app.pipeline.relevance import keyword_in_text
from app.schemas import HotspotEventDTO
from app.services.llm_observability_service import (
    build_cache_key,
    get_cached_analysis,
    log_llm_call,
    save_analysis_cache,
)

logger = logging.getLogger(__name__)


CATEGORY_KEYWORDS = {
    "AI / 大模型": [
        "AI",
        "LLM",
        "Agent",
        "大模型",
        "模型",
        "智能体",
        "机器人",
        "OpenAI",
        "DeepSeek",
        "Claude",
        "Gemini",
        "Transformer",
        "推理",
        "训练",
        "artificial intelligence",
        "machine learning",
        "deep learning",
        "inference",
        "neural",
        "LLMs",
        "AutoGPT",
        "ChatGPT",
        "Qwen",
        "GPT",
    ],
    "计算机技术": [
        "operating system", "distributed", "database", "PostgreSQL", "Redis",
        "SQLite", "network", "networking", "security", "vulnerability",
        "compiler", "compilers", "kernel", "cloud", "storage", "algorithm",
        "algorithms", "CPU", "计算机", "操作系统", "分布式", "数据库",
        "网络", "安全", "漏洞", "编译器", "云计算", "存储", "算法",
    ],
    "开源技术": [
        "GitHub",
        "开源",
        "Linux",
        "Python",
        "Rust",
        "JavaScript",
        "TypeScript",
        "Kubernetes",
        "Docker",
        "数据库",
        "API",
        "SDK",
        "框架",
        "漏洞",
        "安全",
    ],
    "科技产品": [
        "华为",
        "鸿蒙",
        "HarmonyOS",
        "苹果",
        "iPhone",
        "特斯拉",
        "芯片",
        "算力",
        "GPU",
        "手机",
        "汽车",
        "设备",
        "Nvidia",
        "AMD",
        "Intel",
        "chip",
        "chips",
        "smartphone",
        "hardware",
    ],
    "社会民生": [
        "台风",
        "高温",
        "停运",
        "停航",
        "教育",
        "医疗",
        "就业",
        "消费",
        "文旅",
        "天气",
        "出行",
    ],
    "财经商业": [
        "财报",
        "交付",
        "股价",
        "上市",
        "融资",
        "企业",
        "公司",
        "品牌",
        "市场",
        "价格战",
        "营收",
    ],
    # 与 SOURCE_CATEGORY_HINTS 保持一致：来源命中「政策监管」后，关键词分类也必须能产出同一类别，
    # 否则来源分类与关键词分类两套口径不自洽，下游统计会错乱。
    "政策监管": [
        "政策",
        "监管",
        "部委",
        "发改委",
        "工信部",
        "网信办",
        "央行",
        "国务院",
        "法规",
        "条例",
        "规定",
        "通知",
        "合规",
        "整治",
        "约谈",
        "反垄断",
    ],
}

HIGH_RISK_WORDS = ["事故", "灾难", "死亡", "去世", "爆炸", "诈骗", "造谣", "泄露", "违法", "维权"]
MEDIUM_RISK_WORDS = ["争议", "下架", "停运", "停航", "台风", "高温", "漏洞", "渗透", "价格战", "投诉", "诉讼", "风险"]


SOURCE_CATEGORY_HINTS = {
    "github": "开源技术",
    "hackernews": "计算机技术",
    "huggingface": "AI / 大模型",
    "devto": "计算机技术",
}


def classify_by_rules(text: str) -> str:
    """根据关键词做轻量分类。

    这是 LLM 失败或不分析时的兜底逻辑，不追求 NLP 完美，但必须保证输出可读。

    采用「各类命中计分取最高」而非「首个命中即返回」：后者按字典插入顺序遍历，
    只要标题里出现排在前面类别的任一关键词（如 AI/模型/安全/API）就会被优先误分类，
    即使它其实更偏其他类别。计分取最高可显著降低这类误分类。
    """
    lowered = text.lower()
    best_category = "综合"
    best_score = 0
    for category, words in CATEGORY_KEYWORDS.items():
        score = sum(1 for word in words if keyword_in_text(word, lowered))
        # 严格大于：分数相同时保留插入顺序靠前的类别，行为可预期。
        if score > best_score:
            best_score = score
            best_category = category
    return best_category


def classify_event(event: HotspotEventDTO) -> str:
    """Classify the subject, not its host; synthetic connector tags are not evidence."""
    category = classify_by_rules(event.title)
    if category != "综合":
        return category
    category = classify_by_rules(" ".join((item.content or "")[:500] for item in event.items))
    if category != "综合":
        return category
    hints = {SOURCE_CATEGORY_HINTS[source] for source in event.source_codes if source in SOURCE_CATEGORY_HINTS}
    for item in event.items:
        if item.source == "arxiv_ai":
            primary = item.raw_payload.get("primary_category", "")
            hints.add("AI / 大模型" if primary in {"cs.AI", "cs.CL", "cs.LG", "cs.CV", "cs.NE"} else "计算机技术")
    # Stable precedence for ambiguous cross-source events, independent of item order.
    for category in ("AI / 大模型", "计算机技术", "开源技术"):
        if category in hints:
            return category
    return "综合"


def risk_by_rules(title: str) -> tuple[str, str]:
    """根据标题做风险判断。"""
    if any(word in title for word in HIGH_RISK_WORDS):
        return "HIGH", "标题包含事故、违法、诈骗、泄露等高敏感词，建议谨慎处理并等待权威信息确认。"
    if any(word in title for word in MEDIUM_RISK_WORDS):
        return "MEDIUM", "话题可能涉及舆情、公共安全、技术安全或争议内容，适合观察和客观分析。"
    return "LOW", "暂未命中明显高风险词，可作为普通热点观察。"


def _build_content_suggestions(event: HotspotEventDTO, target_industry: str, risk_level: str) -> list[str]:
    """按来源生成更贴近项目定位的选题建议。"""
    sources = set(event.source_codes)
    if risk_level in {"MEDIUM", "HIGH"}:
        return [
            "先做事实梳理和风险提示，不建议直接情绪化借势。",
            "引用权威来源，避免把未确认信息写成确定结论。",
        ]

    if sources & {"github", "hackernews", "arxiv_ai", "huggingface", "devto"}:
        return [
            f"围绕“{target_industry}”整理成技术趋势卡片。",
            "提炼对产品判断、研发规划或内容选题有用的技术启发。",
            "如果连续多日出现，可升级为专题复盘或知识库材料。",
        ]
    return [
        f"结合“{target_industry}”判断是否值得继续追踪。",
        "从事实、影响、风险、行动建议四个角度做短评。",
        "如果与主线弱相关，可只放入综合热点观察区。",
    ]


def fallback_analysis(event: HotspotEventDTO, target_industry: str) -> HotspotEventDTO:
    """LLM 不可用时的规则兜底分析。"""
    risk_level, risk_reason = risk_by_rules(event.title)
    category = classify_event(event)
    source_text = "、".join(event.source_codes) if event.source_codes else "未知来源"

    event.category = category
    event.risk_level = risk_level  # type: ignore[assignment]
    event.risk_reason = risk_reason
    event.summary = f"该热点来自 {event.source_count} 个来源（{source_text}），当前热度 {event.heat_score}/100，核心关注点是：{event.title}。"
    event.main_opinions = [
        "该话题在当前信息流中具备一定关注度，适合纳入今日早报观察。",
        f"从{target_industry}角度，可以关注它对产品判断、技术趋势或业务机会的启发。",
    ]
    if event.historical_insights:
        event.main_opinions.append(event.historical_insights[0])
    event.opposing_opinions = ["单一榜单或单一来源不能代表完整趋势，建议结合后续多源变化继续验证。"]
    event.content_suggestions = _build_content_suggestions(event, target_industry, risk_level)
    if event.business_relevance_reason:
        event.content_suggestions.append(f"业务关联判断：{event.business_relevance_reason}")
    event.analysis_mode = event.analysis_mode or "RULE"
    return event


def apply_langchain_result(
    event: HotspotEventDTO,
    result: HotspotAnalysisResult,
    target_industry: str,
    provider: AIModelProvider | None = None,
    analysis_mode: str = "LLM",
) -> HotspotEventDTO:
    """把 LangChain 结构化结果合并回事件。

    先执行规则分析补齐基础字段；再用 LLM 输出覆盖质量更高的字段。
    这样即使模型只返回了部分字段，前端也不会出现空值或问号模板。
    """
    event = fallback_analysis(event, target_industry)
    if result.summary:
        event.summary = result.summary
    if result.category and result.category != "综合":
        event.category = result.category

    risk = result.risk_level.upper().strip()
    event.risk_level = risk if risk in {"LOW", "MEDIUM", "HIGH"} else event.risk_level  # type: ignore[assignment]
    if result.risk_reason:
        event.risk_reason = result.risk_reason

    if result.main_opinions:
        event.main_opinions = result.main_opinions[:5]
    if result.opposing_opinions:
        event.opposing_opinions = result.opposing_opinions[:5]
    if result.content_suggestions:
        event.content_suggestions = result.content_suggestions[:5]
    if event.business_relevance_reason and not any("业务关联" in item for item in event.content_suggestions):
        event.content_suggestions.append(f"业务关联判断：{event.business_relevance_reason}")
    event.analysis_mode = analysis_mode
    event.analysis_model = provider.model if provider else settings.ai_model
    event.analysis_error = None if analysis_mode == "LLM" else "复用 LLM 缓存结果，部分字段由规则兜底补齐"
    return event


def analyze_events(
    events: list[HotspotEventDTO],
    target_industry: str,
    limit: int = 30,
    providers: list[AIModelProvider] | None = None,
    db: Session | None = None,
    run_id: str | None = None,
    use_cache: bool = True,
) -> list[HotspotEventDTO]:
    """分析热点事件。

    Top N 尝试使用 LangChain + LLM；其余或失败项走规则兜底。
    """
    analyzed: list[HotspotEventDTO] = []
    fallback_analyzer = LangChainHotspotAnalyzer()
    active_providers = providers or []
    llm_enabled = bool(active_providers) or fallback_analyzer.available()

    for idx, event in enumerate(events):
        should_try_llm = idx < limit and llm_enabled
        started = time.perf_counter()
        langchain_result: HotspotAnalysisResult | None = None
        used_provider: AIModelProvider | None = None
        used_cache = False
        last_error: str | None = None

        if should_try_llm and active_providers:
            # 多 Provider 按优先级尝试：主模型失败后自动换下一个模型。
            for provider in active_providers:
                cache_key: str | None = None
                prompt_hash: str | None = None

                if db and use_cache:
                    try:
                        cache_key, prompt_hash = build_cache_key(event, target_industry, provider)
                        cache_started = time.perf_counter()
                        cached_result = get_cached_analysis(db, cache_key)
                        if cached_result:
                            langchain_result = cached_result
                            used_provider = provider
                            used_cache = True
                            log_llm_call(
                                db,
                                run_id=run_id,
                                event=event,
                                provider=provider,
                                status="CACHE_HIT",
                                latency_ms=int((time.perf_counter() - cache_started) * 1000),
                                cache_hit=True,
                                prompt_hash=prompt_hash,
                                cache_key=cache_key,
                            )
                            break
                    except Exception as exc:  # noqa: BLE001
                        last_error = f"读取 LLM 缓存失败：{exc}"
                        logger.warning("读取 LLM 缓存失败: %s", exc)

                call_started = time.perf_counter()
                analyzer = LangChainHotspotAnalyzer(provider=provider)
                result = analyzer.analyze(event, target_industry)
                call_latency_ms = int((time.perf_counter() - call_started) * 1000)

                if result:
                    langchain_result = result
                    used_provider = provider
                    if db:
                        try:
                            log_llm_call(
                                db,
                                run_id=run_id,
                                event=event,
                                provider=provider,
                                status="SUCCESS",
                                latency_ms=call_latency_ms,
                                cache_hit=False,
                                prompt_hash=prompt_hash,
                                cache_key=cache_key,
                                usage=analyzer.last_usage,
                            )
                            if cache_key and prompt_hash:
                                save_analysis_cache(
                                    db,
                                    event=event,
                                    target_industry=target_industry,
                                    provider=provider,
                                    cache_key=cache_key,
                                    prompt_hash=prompt_hash,
                                    result=result,
                                )
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("保存 LLM 调用日志或缓存失败: %s", exc)
                    break

                last_error = f"{provider.name}({provider.model}): {analyzer.last_error}"
                if db:
                    try:
                        log_llm_call(
                            db,
                            run_id=run_id,
                            event=event,
                            provider=provider,
                            status="FAILED",
                            latency_ms=call_latency_ms,
                            cache_hit=False,
                            prompt_hash=prompt_hash,
                            cache_key=cache_key,
                            error_message=analyzer.last_error,
                            usage=analyzer.last_usage,
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("保存 LLM 失败日志失败: %s", exc)

        elif should_try_llm:
            cache_key = None
            prompt_hash = None
            if db and use_cache:
                try:
                    cache_key, prompt_hash = build_cache_key(event, target_industry, None)
                    cache_started = time.perf_counter()
                    cached_result = get_cached_analysis(db, cache_key)
                    if cached_result:
                        langchain_result = cached_result
                        used_cache = True
                        log_llm_call(
                            db,
                            run_id=run_id,
                            event=event,
                            provider=None,
                            status="CACHE_HIT",
                            latency_ms=int((time.perf_counter() - cache_started) * 1000),
                            cache_hit=True,
                            prompt_hash=prompt_hash,
                            cache_key=cache_key,
                        )
                except Exception as exc:  # noqa: BLE001
                    last_error = f"读取 LLM 缓存失败：{exc}"

            if not langchain_result:
                call_started = time.perf_counter()
                langchain_result = fallback_analyzer.analyze(event, target_industry)
                call_latency_ms = int((time.perf_counter() - call_started) * 1000)
                last_error = fallback_analyzer.last_error
                if db:
                    try:
                        log_llm_call(
                            db,
                            run_id=run_id,
                            event=event,
                            provider=None,
                            status="SUCCESS" if langchain_result else "FAILED",
                            latency_ms=call_latency_ms,
                            cache_hit=False,
                            prompt_hash=prompt_hash,
                            cache_key=cache_key,
                            error_message=None if langchain_result else fallback_analyzer.last_error,
                            usage=fallback_analyzer.last_usage,
                        )
                        if langchain_result and cache_key and prompt_hash:
                            save_analysis_cache(
                                db,
                                event=event,
                                target_industry=target_industry,
                                provider=None,
                                cache_key=cache_key,
                                prompt_hash=prompt_hash,
                                result=langchain_result,
                            )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("保存 LLM 调用日志或缓存失败: %s", exc)

        latency_ms = int((time.perf_counter() - started) * 1000) if should_try_llm else None

        if langchain_result:
            event = apply_langchain_result(
                event,
                langchain_result,
                target_industry,
                used_provider,
                analysis_mode="LLM_CACHE" if used_cache else "LLM",
            )
            event.analysis_latency_ms = latency_ms
        else:
            event = fallback_analysis(event, target_industry)
            event.analysis_latency_ms = latency_ms
            if should_try_llm:
                event.analysis_mode = "RULE_FALLBACK"
                event.analysis_model = used_provider.model if used_provider else settings.ai_model
                event.analysis_error = last_error or "LLM 调用失败，已降级为规则分析"
            elif idx >= limit:
                event.analysis_mode = "RULE"
                event.analysis_error = "未进入 LLM Top N，使用规则分析"
            else:
                event.analysis_mode = "RULE"
                event.analysis_error = "未配置可用模型，使用规则分析"
        analyzed.append(event)
    return analyzed
