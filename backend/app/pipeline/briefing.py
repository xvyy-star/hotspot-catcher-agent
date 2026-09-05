"""今日早报生成模块。"""
from __future__ import annotations

from datetime import date
from collections import Counter
from urllib.parse import urlparse

from app.pipeline.evidence import has_real_evidence
from app.pipeline.relevance import event_matches_product_focus
from app.schemas import BriefingDTO, HotspotEventDTO


def _short_text(value: str | None, max_len: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _domain(url: str | None) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url).netloc
    except Exception:
        return ""
    return host.replace("www.", "")


def _format_evidence(event: HotspotEventDTO, max_items: int = 4) -> list[str]:
    """把事件底层 raw items 转成可追溯来源证据。"""
    rows: list[str] = []
    seen: set[str] = set()
    for item in sorted(event.items or [], key=lambda row: (row.rank is None, row.rank or 9999, row.source)):
        if not has_real_evidence(item):
            continue
        key = item.url
        if not key or key in seen:
            continue
        seen.add(key)
        source = item.source_name or item.source
        title = _short_text(item.title, 90)
        rank = f"Rank #{item.rank}" if item.rank else "榜单项"
        heat = f"｜热度 {item.raw_hot_score}" if item.raw_hot_score else ""
        captured = item.captured_at.strftime("%Y-%m-%d %H:%M") if item.captured_at else ""
        captured_text = f"｜采集 {captured}" if captured else ""
        host = _domain(item.url)
        host_text = f"｜{host}" if host else ""
        rows.append(f"- [{title}]({item.url})｜{source}｜{rank}{heat}{host_text}{captured_text}")
        if len(rows) >= max_items:
            break
    return rows


def _credibility_text(event: HotspotEventDTO) -> str:
    score = event.credibility_score or 0
    level = event.credibility_level or "LOW"
    reason = event.credibility_reason or f"{event.source_count} 个来源"
    return f"{score:.0f}/100（{level}，{reason}）"


def generate_markdown(events: list[HotspotEventDTO], briefing_date: date, source_health: dict) -> str:
    """生成 Markdown 早报。

    Markdown 同时适合前端渲染、邮件、企业微信/飞书推送，兼容性好。
    """
    verified_events = [
        event
        for event in events
        if any(has_real_evidence(item) for item in event.items or [])
        and not event.is_fallback_sample
        and event_matches_product_focus(event)
    ]
    category_counter = Counter(event.category for event in verified_events)
    lines: list[str] = []
    lines.append(f"# 今日热点早报｜{briefing_date.isoformat()}")
    lines.append("")
    lines.append("## 一、今日总览")
    lines.append(f"今日共识别 {len(verified_events)} 个带原文链接的真实热点事件。")
    lines.append("数据准入：只保留非样例/非模拟，且具备 item 级 http(s) 原文链接的公开数据。")
    if category_counter:
        lines.append("分类分布：" + "、".join(f"{k} {v} 条" for k, v in category_counter.most_common()))
    lines.append("")
    lines.append("## 二、数据源状态")
    for source, meta in source_health.items():
        if str(source).startswith("_"):
            continue
        if not isinstance(meta, dict):
            continue
        source_url = meta.get("source_url") or "-"
        dropped = meta.get("dropped_fallback_count", 0)
        dropped_no_evidence = meta.get("dropped_no_evidence_count", 0)
        lines.append(
            f"- {source}: {meta.get('status')}，真实入库 {meta.get('real_count', 0)} 条，"
            f"样例/模拟入库 {meta.get('fallback_count', 0)} 条，拦截样例 {dropped} 条，"
            f"拦截无原文链接 {dropped_no_evidence} 条，来源：{source_url}"
        )
    lines.append("")
    lines.append("## 三、今日最值得关注 Top 10")
    for idx, event in enumerate(verified_events[:10], start=1):
        lines.append(f"### {idx}. {event.title}")
        lines.append(f"- 结论：{_short_text(event.summary, 220) or '暂无摘要'}")
        lines.append(f"- 为什么重要：{_short_text(event.business_relevance_reason, 220) or '需要结合业务场景继续判断。'}")
        lines.append(f"- 热度：{event.heat_score}/100")
        lines.append(f"- 可信度：{_credibility_text(event)}")
        lines.append(f"- 平台：{', '.join(event.source_codes)}｜来源数：{event.source_count}")
        lines.append(f"- 分类：{event.category}")
        lines.append(f"- 风险：{event.risk_level}｜{event.risk_reason}")
        lines.append("- 来源证据：")
        evidence_rows = _format_evidence(event)
        if evidence_rows:
            lines.extend(evidence_rows)
        else:
            lines.append("- 已被真实数据闸门过滤：缺少 item 级原文链接。")
        if event.business_relevance and event.business_relevance != "UNKNOWN":
            lines.append(f"- 业务关联度：{event.business_relevance}｜{event.business_relevance_reason}")
        if event.historical_insights:
            lines.append("- 知识库关联：" + "；".join(event.historical_insights[:2]))
        if event.rag_references:
            refs = []
            for ref in event.rag_references[:2]:
                refs.append(
                    f"《{ref.get('document_title', '未知文档')}》chunk#{ref.get('chunk_index', '-')}"
                    f"（score={ref.get('score', 0)}）"
                )
            lines.append("- RAG 引用：" + "；".join(refs))
        if event.main_opinions:
            lines.append("- 主流观点：" + "；".join(event.main_opinions[:2]))
        if event.content_suggestions:
            lines.append("- 建议动作：" + "；".join(event.content_suggestions[:2]))
        lines.append("")
    risk_events = [event for event in verified_events if event.risk_level in {"MEDIUM", "HIGH"}]
    if risk_events:
        lines.append("## 四、风险预警")
        for event in risk_events[:5]:
            lines.append(f"- {event.title}：{event.risk_reason}")
        lines.append("")
    lines.append("## 五、运营建议")
    lines.append("- 优先选择 LOW 风险且与业务强相关的话题做内容。")
    lines.append("- MEDIUM/HIGH 风险话题建议先观察舆论，不要直接借势营销。")
    lines.append("- 对连续多日出现的平台共振话题，可升级为专题分析。")
    return "\n".join(lines)


def build_briefing(events: list[HotspotEventDTO], briefing_date: date, source_health: dict) -> BriefingDTO:
    verified_events = [
        event
        for event in events
        if any(has_real_evidence(item) for item in event.items or [])
        and not event.is_fallback_sample
        and event_matches_product_focus(event)
    ]
    top_titles = "、".join(event.title for event in verified_events[:3])
    summary = f"今日重点关注：{top_titles}" if top_titles else "今日暂无可用热点数据。"
    markdown = generate_markdown(verified_events, briefing_date, source_health)
    return BriefingDTO(
        briefing_date=briefing_date,
        title=f"今日热点早报｜{briefing_date.isoformat()}",
        summary=summary,
        markdown=markdown,
        events=verified_events,
        source_health=source_health,
        status="SUCCESS" if verified_events else "EMPTY",
    )

