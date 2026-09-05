"""数据访问层。

Repository 的职责是隔离数据库细节：
API / Agent 只关心“保存早报、查询热点”，不关心 ORM 怎么写。
这样后续从 MySQL 换 PostgreSQL，业务层改动会小很多。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.db.models import AgentRun, DailyBriefing, HotspotEvent, HotspotRawItem
from app.pipeline.evidence import FAKE_SOURCE_CODES, is_fallback_item, is_http_url, split_items_by_evidence
from app.pipeline.relevance import keyword_in_text, TECH_KEYWORDS
from app.services.feedback_service import blocked_event_keys
from app.services.system_log_service import write_system_log
from app.schemas import BriefingDTO, HotspotEventDTO, HotspotItem
from app.core.source_policy import OFFICIAL_SOURCE_CODES


STRONG_SOURCE_CODES = OFFICIAL_SOURCE_CODES
GENERAL_SOURCE_CODES = set()


def _item_is_fallback(item: HotspotItem) -> bool:
    return is_fallback_item(item)


def _raw_row_has_real_evidence(row: HotspotRawItem) -> bool:
    payload = row.raw_payload if isinstance(row.raw_payload, dict) else {}
    source = str(row.source_code or "").strip().lower()
    return source in OFFICIAL_SOURCE_CODES and not payload.get("is_fallback_sample") and is_http_url(row.url)


def _duplicate_is_reusable(row: HotspotRawItem) -> bool:
    """去重命中旧数据时，也必须确认旧行本身有真实原文证据。"""
    return _raw_row_has_real_evidence(row)


def _credibility_for_event(event: HotspotEventDTO) -> tuple[float, str, str, bool]:
    """基于来源数量、来源类型、RAG 引用和样例标记给热点打可信度。"""
    source_codes = set(event.source_codes or [])
    fallback_count = sum(1 for item in event.items if _item_is_fallback(item))
    is_fallback = fallback_count > 0 and fallback_count == len(event.items)
    score = 35.0
    score += min(len(source_codes), 4) * 12
    score += len(source_codes & STRONG_SOURCE_CODES) * 10
    score += len(source_codes & GENERAL_SOURCE_CODES) * 4
    if event.rag_references:
        score += min(len(event.rag_references), 3) * 5
    if event.analysis_mode in {"LLM", "LLM_CACHE"}:
        score += 5
    if is_fallback:
        score -= 35
    score = max(0.0, min(100.0, round(score, 1)))
    if score >= 75:
        level = "HIGH"
    elif score >= 55:
        level = "MEDIUM"
    else:
        level = "LOW"
    reasons: list[str] = []
    if source_codes:
        if len(source_codes) >= 2:
            reasons.append(f"{len(source_codes)} 个来源交叉验证")
        else:
            reasons.append("1 个来源，需继续观察")
    if source_codes & STRONG_SOURCE_CODES:
        reasons.append("包含开发者/科技/论文等强技术源")
    if event.rag_references:
        reasons.append(f"{len(event.rag_references)} 条知识库引用")
    if is_fallback:
        reasons.append("当前为本地样例兜底，不能当作实时事实")
    if not reasons:
        reasons.append("来源信息不足，仅作低置信参考")
    return score, level, "；".join(reasons), is_fallback


def _find_recent_raw_duplicate(db: Session, item: HotspotItem) -> HotspotRawItem | None:
    """查找近期已保存的相同 raw_item，避免重复抓取导致数据库膨胀。"""
    cutoff = datetime.utcnow() - timedelta(days=7)
    base = select(HotspotRawItem).where(
        HotspotRawItem.source_code == item.source,
        HotspotRawItem.captured_at >= cutoff,
    )
    if item.source_item_id:
        row = db.execute(
            base.where(HotspotRawItem.source_item_id == item.source_item_id)
            .order_by(desc(HotspotRawItem.captured_at), desc(HotspotRawItem.id))
            .limit(1)
        ).scalar_one_or_none()
        if row:
            if _duplicate_is_reusable(row):
                return row
    if item.url:
        row = db.execute(
            base.where(HotspotRawItem.url == item.url)
            .order_by(desc(HotspotRawItem.captured_at), desc(HotspotRawItem.id))
            .limit(1)
        ).scalar_one_or_none()
        if row:
            if _duplicate_is_reusable(row):
                return row
    title = (item.title or "").strip()
    if title:
        row = db.execute(
            base.where(HotspotRawItem.title == title)
            .order_by(desc(HotspotRawItem.captured_at), desc(HotspotRawItem.id))
            .limit(1)
        ).scalar_one_or_none()
        if row and _duplicate_is_reusable(row):
            return row
    return None


def save_raw_items(db: Session, items: list[HotspotItem]) -> list[int]:
    """保存原始热点并返回数据库 ID 列表。

    同一来源、同一天的完全相同观测复用旧记录；变化或跨日观测保存新快照。
    原始证据保持不可变，历史事件仍引用当时的排名、热度与内容。
    """
    accepted_items, dropped_fallback_count, dropped_no_evidence_count = split_items_by_evidence(items)
    if dropped_fallback_count or dropped_no_evidence_count:
        write_system_log(
            db,
            level="WARNING",
            module="data-quality",
            message="raw_item 入库前拦截非真实数据",
            extra={"dropped_fallback_count": dropped_fallback_count, "dropped_no_evidence_count": dropped_no_evidence_count},
        )
        # 保持调用方的 items 与返回 id 一一对应，避免后续 raw_payload._db_id 回填错位。
        items[:] = accepted_items

    ids: list[int] = []
    for item in accepted_items:
        existing = _find_recent_raw_duplicate(db, item)
        if existing and existing.captured_at.date() == item.captured_at.date() and all(
            getattr(existing, field) == getattr(item, field)
            for field in ("source_name", "source_item_id", "title", "url", "rank", "raw_hot_score", "content", "tags")
        ) and {k: v for k, v in (existing.raw_payload if isinstance(existing.raw_payload, dict) else {}).items() if k != "_db_id"} == {
            k: v for k, v in item.raw_payload.items() if k != "_db_id"
        }:
            ids.append(existing.id)
            continue
        row = HotspotRawItem(
            source_code=item.source,
            source_name=item.source_name,
            source_item_id=item.source_item_id,
            title=item.title,
            url=item.url,
            rank=item.rank,
            raw_hot_score=item.raw_hot_score,
            content=item.content,
            tags=item.tags,
            raw_payload={k: v for k, v in item.raw_payload.items() if k != "_db_id"},
            captured_at=item.captured_at,
        )
        db.add(row)
        db.flush()
        ids.append(row.id)
    return ids


def upsert_events(db: Session, events: list[HotspotEventDTO]) -> None:
    """保存热点事件。

    使用 event_key 做幂等：同一事件重复生成时更新，而不是插入重复数据。
    """
    # SessionLocal 关闭了 autoflush，同一批 events 如果出现重复 event_key，
    # 第二次查询数据库时看不到前一次还未 flush 的 pending insert，最后会在统一 flush 时撞唯一索引。
    # 所以这里先做一层批内去重，保证一次任务不会因为单个重复热点拖垮整份早报。
    seen_event_keys: set[str] = set()
    for event in events:
        event.items, dropped_fallback_count, dropped_no_evidence_count = split_items_by_evidence(event.items or [])
        if dropped_fallback_count or dropped_no_evidence_count:
            write_system_log(
                db,
                level="WARNING",
                module="data-quality",
                message=f"事件入库前拦截无真实证据条目：{event.title}",
                extra={
                    "event_key": event.event_key,
                    "dropped_fallback_count": dropped_fallback_count,
                    "dropped_no_evidence_count": dropped_no_evidence_count,
                },
            )
        if not event.items:
            continue
        if event.event_key in seen_event_keys:
            continue
        seen_event_keys.add(event.event_key)
        existing = db.execute(select(HotspotEvent).where(HotspotEvent.event_key == event.event_key)).scalar_one_or_none()
        first_seen = min((item.captured_at for item in event.items), default=datetime.utcnow())
        last_seen = max((item.captured_at for item in event.items), default=datetime.utcnow())
        raw_ids = [item.raw_payload.get("_db_id") for item in event.items if isinstance(item.raw_payload, dict) and item.raw_payload.get("_db_id")]
        credibility_score, credibility_level, credibility_reason, is_fallback_sample = _credibility_for_event(event)
        # 回写到 DTO，确保随后保存到 daily_briefing.raw_json / Markdown 的也是已计算值，
        # 否则前端情报卡会拿到 Pydantic 默认的 0 / LOW。
        event.credibility_score = credibility_score
        event.credibility_level = credibility_level
        event.credibility_reason = credibility_reason
        event.is_fallback_sample = is_fallback_sample
        if existing:
            existing.title = event.title
            existing.summary = event.summary
            existing.category = event.category
            existing.heat_score = event.heat_score
            existing.risk_level = event.risk_level
            existing.risk_reason = event.risk_reason
            existing.source_codes = event.source_codes
            existing.source_count = event.source_count
            existing.main_opinions = event.main_opinions
            existing.opposing_opinions = event.opposing_opinions
            existing.content_suggestions = event.content_suggestions
            existing.rag_references = event.rag_references
            existing.historical_insights = event.historical_insights
            existing.knowledge_relevance_score = event.knowledge_relevance_score
            existing.knowledge_relevance_level = event.knowledge_relevance_level
            existing.business_relevance = event.business_relevance
            existing.business_relevance_reason = event.business_relevance_reason
            existing.analysis_mode = event.analysis_mode
            existing.analysis_model = event.analysis_model
            existing.analysis_latency_ms = event.analysis_latency_ms
            existing.analysis_error = event.analysis_error
            existing.credibility_score = credibility_score
            existing.credibility_level = credibility_level
            existing.credibility_reason = credibility_reason
            existing.is_fallback_sample = is_fallback_sample
            existing.raw_item_ids = raw_ids
            existing.last_seen_at = last_seen
        else:
            db.add(
                HotspotEvent(
                    event_key=event.event_key,
                    title=event.title,
                    summary=event.summary,
                    category=event.category,
                    heat_score=event.heat_score,
                    risk_level=event.risk_level,
                    risk_reason=event.risk_reason,
                    source_codes=event.source_codes,
                    source_count=event.source_count,
                    main_opinions=event.main_opinions,
                    opposing_opinions=event.opposing_opinions,
                    content_suggestions=event.content_suggestions,
                    rag_references=event.rag_references,
                    historical_insights=event.historical_insights,
                    knowledge_relevance_score=event.knowledge_relevance_score,
                    knowledge_relevance_level=event.knowledge_relevance_level,
                    business_relevance=event.business_relevance,
                    business_relevance_reason=event.business_relevance_reason,
                    analysis_mode=event.analysis_mode,
                    analysis_model=event.analysis_model,
                    analysis_latency_ms=event.analysis_latency_ms,
                    analysis_error=event.analysis_error,
                    credibility_score=credibility_score,
                    credibility_level=credibility_level,
                    credibility_reason=credibility_reason,
                    is_fallback_sample=is_fallback_sample,
                    raw_item_ids=raw_ids,
                    first_seen_at=first_seen,
                    last_seen_at=last_seen,
                )
            )


def save_briefing(db: Session, briefing: BriefingDTO) -> DailyBriefing:
    """保存每日早报。

    briefing_date 唯一，重复生成时覆盖当天版本。
    """
    existing = db.execute(select(DailyBriefing).where(DailyBriefing.briefing_date == briefing.briefing_date)).scalar_one_or_none()
    raw_json = briefing.model_dump(mode="json")
    if existing:
        existing.title = briefing.title
        existing.summary = briefing.summary
        existing.markdown = briefing.markdown
        existing.raw_json = raw_json
        existing.status = briefing.status
        return existing
    row = DailyBriefing(
        briefing_date=briefing.briefing_date,
        title=briefing.title,
        summary=briefing.summary,
        markdown=briefing.markdown,
        raw_json=raw_json,
        status=briefing.status,
    )
    db.add(row)
    db.flush()
    return row


def create_run(db: Session, run_id: str, status: str = "RUNNING", meta: dict | None = None) -> AgentRun:
    existing = db.execute(select(AgentRun).where(AgentRun.run_id == run_id)).scalar_one_or_none()
    if existing:
        existing.status = status
        existing.started_at = datetime.utcnow()
        existing.finished_at = None
        existing.error_message = None
        existing.meta = {**(existing.meta or {}), **(meta or {})}
        db.flush()
        write_system_log(db, level="INFO", module="agent", message=f"Agent 任务状态更新：{status}", run_id=run_id)
        return existing
    row = AgentRun(run_id=run_id, status=status, meta=meta)
    db.add(row)
    db.flush()
    write_system_log(db, level="INFO", module="agent", message=f"Agent 任务创建：{status}", run_id=run_id)
    return row


def finish_run(db: Session, run_id: str, status: str, total_raw: int = 0, total_events: int = 0, error_message: str | None = None, meta: dict | None = None) -> None:
    row = db.execute(select(AgentRun).where(AgentRun.run_id == run_id)).scalar_one_or_none()
    if not row:
        return
    row.status = status
    row.finished_at = datetime.utcnow()
    row.total_raw = total_raw
    row.total_events = total_events
    row.error_message = error_message
    row.meta = meta
    write_system_log(
        db,
        level="ERROR" if status == "FAILED" else "INFO",
        module="agent",
        message=f"Agent 任务结束：{status}，raw={total_raw}，events={total_events}",
        run_id=run_id,
        extra={"total_raw": total_raw, "total_events": total_events, "error_message": error_message},
    )


def get_today_briefing(db: Session) -> DailyBriefing | None:
    return db.execute(select(DailyBriefing).where(DailyBriefing.briefing_date == date.today())).scalar_one_or_none()


def get_briefing_by_date(db: Session, briefing_date: date) -> DailyBriefing | None:
    """按日期查询已归档早报。

    历史早报页面只读这张表，不重新计算，保证用户看到的是当时保存下来的版本。
    """
    return db.execute(select(DailyBriefing).where(DailyBriefing.briefing_date == briefing_date)).scalar_one_or_none()


def list_briefings(db: Session, limit: int = 30) -> list[DailyBriefing]:
    return list(db.execute(select(DailyBriefing).order_by(desc(DailyBriefing.briefing_date)).limit(limit)).scalars())


def list_briefing_summaries(db: Session, limit: int = 30) -> list[dict]:
    """查询历史早报列表摘要。

    注意不要在列表页 SELECT `markdown/raw_json` 两个大字段。
    否则 MySQL 排序时可能把超大 JSON 一起放进 sort buffer，触发：
    `Out of sort memory, consider increasing server sort buffer size`。

    企业级列表页常见做法也是“列表轻量字段 + 详情按需加载”。
    """
    rows = db.execute(
        select(
            DailyBriefing.id,
            DailyBriefing.briefing_date,
            DailyBriefing.title,
            DailyBriefing.summary,
            DailyBriefing.status,
            DailyBriefing.created_at,
            DailyBriefing.updated_at,
        )
        .order_by(desc(DailyBriefing.briefing_date))
        .limit(limit)
    ).mappings()
    return [dict(row) for row in rows]


def _normalize_source_codes(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part for part in value.replace(",", " ").split() if part]
    return []


def _looks_mojibake(*values) -> bool:
    """识别历史数据库中已经被错误编码的中文，避免继续污染交付演示。"""
    text = " ".join(str(value or "") for value in values)
    if not text:
        return False
    markers = ("Ã", "Â", "â€", "ä", "å", "æ", "ç", "è", "é", "ï¼", "ã", "�")
    return sum(text.count(marker) for marker in markers) >= 2


def _event_matches_current_lane(row: HotspotEvent) -> bool:
    """只展示当前产品定位需要的 AI / 科技 / 产业情报事件。"""
    general_sources = set()
    strong_tech_sources = {"github", "arxiv_ai", "huggingface", "devto"}
    developer_sources = {"hackernews"}
    preferred_sources = general_sources | strong_tech_sources | developer_sources
    preferred_categories = {"AI / 大模型", "计算机技术", "开源技术", "科技产品", "财经商业", "技术", "商业"}
    tech_keywords = {
        "ai", "agent", "llm", "openai", "deepseek", "github", "transformer",
        "人工智能", "大模型", "开源", "芯片", "算力", "机器人", "自动驾驶", "量子",
        "软件", "编程", "开发者", "互联网", "云计算", "数据库", "操作系统", "安全",
        "硬件", "显卡", "英伟达", "特斯拉", "苹果", "微软", "谷歌",
    }
    policy_keywords = {
        "\u516c\u8003", "\u7533\u8bba", "\u56fd\u8003", "\u7701\u8003", "\u4e8b\u4e1a\u7f16",
        "\u9762\u8bd5", "\u65f6\u653f", "总书记", "共产党",
        "国务院", "人大", "政协", "两会", "政治", "改革精神", "高质量发展", "青年干部",
    }
    source_codes = set(_normalize_source_codes(row.source_codes))

    if source_codes and source_codes.isdisjoint(preferred_sources):
        return False
    if not source_codes or not source_codes.issubset(OFFICIAL_SOURCE_CODES):
        return False

    category = row.category or ""
    if _looks_mojibake(row.title, row.summary, category, row.risk_reason, row.business_relevance_reason):
        return False

    content_text = " ".join(
        [
            row.title or "",
            row.summary or "",
            row.risk_reason or "",
            row.business_relevance_reason or "",
        ]
    ).lower()
    scoped_text = f"{content_text} {category}".lower()
    headline_text = (row.title or "").lower()

    if any(keyword in content_text for keyword in policy_keywords):
        return False

    if source_codes & strong_tech_sources:
        return True

    has_explicit_tech_signal = any(keyword_in_text(keyword, content_text) for keyword in tech_keywords | TECH_KEYWORDS)
    has_headline_tech_signal = any(keyword_in_text(keyword, headline_text) for keyword in tech_keywords | TECH_KEYWORDS)
    if source_codes & (general_sources | developer_sources):
        # 百度/头条/B站/HN 都可能出现泛热点；这里只信标题里的显式技术词，
        # 不让 category 或来源本身单独放行。
        return has_headline_tech_signal

    return category in preferred_categories and any(keyword.lower() in scoped_text for keyword in tech_keywords)


def list_events(db: Session, limit: int = 100, category: str | None = None, risk_level: str | None = None) -> list[HotspotEvent]:
    stmt = (
        select(HotspotEvent)
        .where(HotspotEvent.is_fallback_sample.is_(False))
        .order_by(desc(HotspotEvent.heat_score), desc(HotspotEvent.updated_at))
        .limit(max(limit * 20, 100))
    )
    if category:
        stmt = stmt.where(HotspotEvent.category == category)
    if risk_level:
        stmt = stmt.where(HotspotEvent.risk_level == risk_level)
    rows = list(db.execute(stmt).scalars())
    blocked_keys = blocked_event_keys(db)
    filtered: list[HotspotEvent] = []
    for row in rows:
        if row.event_key in blocked_keys:
            continue
        if not _event_matches_current_lane(row):
            continue
        if not _event_row_has_real_evidence(db, row):
            continue
        filtered.append(row)
        if len(filtered) >= limit:
            break
    return filtered


def _event_row_has_real_evidence(db: Session, row: HotspotEvent) -> bool:
    """事件表对外展示前再次核验 raw_item 证据。"""
    raw_ids = []
    for value in _normalize_source_codes(row.raw_item_ids):
        try:
            raw_ids.append(int(value))
        except (TypeError, ValueError):
            continue
    if not raw_ids:
        return False
    raw_rows = db.execute(select(HotspotRawItem).where(HotspotRawItem.id.in_(raw_ids[:20]))).scalars()
    return any(_raw_row_has_real_evidence(raw) for raw in raw_rows)


def list_runs(db: Session, limit: int = 20) -> list[AgentRun]:
    return list(db.execute(select(AgentRun).order_by(desc(AgentRun.started_at)).limit(limit)).scalars())
