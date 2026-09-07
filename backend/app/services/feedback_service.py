"""热点情报人工反馈服务。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.db.models import HotspotEvent, HotspotEventFeedback


VALID_FEEDBACK_ACTIONS = {"USEFUL", "IRRELEVANT", "FAVORITE", "BLOCK"}
VALID_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH"}
POSITIVE_ACTIONS = {"USEFUL", "FAVORITE"}
NEGATIVE_ACTIONS = {"IRRELEVANT", "BLOCK"}
BLOCK_ACTION = "BLOCK"


class FeedbackEventNotFoundError(LookupError):
    """Raised when feedback targets an event that is not in the event pool."""


def normalize_feedback_action(action: str) -> str:
    value = str(action or "").strip().upper()
    if value not in VALID_FEEDBACK_ACTIONS:
        raise ValueError(f"不支持的反馈类型：{action}")
    return value


def feedback_to_dict(row: HotspotEventFeedback) -> dict[str, Any]:
    return {
        "id": row.id,
        "event_key": row.event_key,
        "action": row.action,
        "note": row.note,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def upsert_event_feedback(
    db: Session,
    *,
    event_key: str,
    action: str,
    note: str | None = None,
    created_by: str = "admin",
) -> HotspotEventFeedback:
    normalized_action = normalize_feedback_action(action)
    normalized_key = str(event_key or "").strip()
    if not normalized_key:
        raise ValueError("event_key 不能为空")
    event_id = db.execute(
        select(HotspotEvent.id).where(HotspotEvent.event_key == normalized_key).limit(1)
    ).scalar_one_or_none()
    if event_id is None:
        raise FeedbackEventNotFoundError(f"情报事件不存在：{normalized_key}")

    row = db.execute(
        select(HotspotEventFeedback).where(
            HotspotEventFeedback.event_key == normalized_key,
            HotspotEventFeedback.action == normalized_action,
            HotspotEventFeedback.created_by == created_by,
        )
    ).scalar_one_or_none()
    if row:
        row.note = (note or "").strip() or row.note
        row.updated_at = datetime.utcnow()
        db.flush()
        return row

    row = HotspotEventFeedback(
        event_key=normalized_key,
        action=normalized_action,
        note=(note or "").strip() or None,
        created_by=created_by,
    )
    db.add(row)
    db.flush()
    return row


def delete_event_feedback(
    db: Session,
    *,
    event_key: str,
    action: str,
    created_by: str = "admin",
) -> int:
    normalized_action = normalize_feedback_action(action)
    normalized_key = str(event_key or "").strip()
    if not normalized_key:
        return 0
    rows = list(
        db.execute(
            select(HotspotEventFeedback).where(
                HotspotEventFeedback.event_key == normalized_key,
                HotspotEventFeedback.action == normalized_action,
                HotspotEventFeedback.created_by == created_by,
            )
        ).scalars()
    )
    for row in rows:
        db.delete(row)
    db.flush()
    return len(rows)


def list_event_feedback(db: Session, *, event_key: str, created_by: str | None = None) -> list[dict[str, Any]]:
    stmt = (
        select(HotspotEventFeedback)
        .where(HotspotEventFeedback.event_key == str(event_key or "").strip())
        .order_by(desc(HotspotEventFeedback.updated_at), desc(HotspotEventFeedback.id))
    )
    if created_by is not None:
        stmt = stmt.where(HotspotEventFeedback.created_by == created_by)
    rows = db.execute(stmt).scalars()
    return [feedback_to_dict(row) for row in rows]


def list_feedback_records(
    db: Session,
    *,
    action: str | None = None,
    keyword: str | None = None,
    category: str | None = None,
    risk_level: str | None = None,
    limit: int = 200,
    created_by: str | None = None,
) -> list[dict[str, Any]]:
    """列出全部人工反馈记录，并补充对应情报的标题和基础指标。

    这些数据是前端“有用 / 无关 / 收藏 / 屏蔽”按钮的落点；单条事件页只看摘要，
    管理页需要能按反馈类型回看和撤销，所以这里提供全量列表。
    """
    limit = max(1, min(int(limit or 200), 500))
    normalized_action = normalize_feedback_action(action) if action else None
    stmt = (
        select(
            HotspotEventFeedback,
            HotspotEvent.title.label("event_title"),
            HotspotEvent.category.label("event_category"),
            HotspotEvent.heat_score.label("event_heat_score"),
            HotspotEvent.risk_level.label("event_risk_level"),
            HotspotEvent.source_count.label("event_source_count"),
            HotspotEvent.credibility_score.label("event_credibility_score"),
            HotspotEvent.credibility_level.label("event_credibility_level"),
        )
        .join(HotspotEvent, HotspotEvent.event_key == HotspotEventFeedback.event_key)
        .order_by(desc(HotspotEventFeedback.updated_at), desc(HotspotEventFeedback.id))
        .limit(limit)
    )
    if created_by is not None:
        stmt = stmt.where(HotspotEventFeedback.created_by == created_by)
    if normalized_action:
        stmt = stmt.where(HotspotEventFeedback.action == normalized_action)
    normalized_category = str(category or "").strip()
    if normalized_category:
        stmt = stmt.where(HotspotEvent.category == normalized_category)
    normalized_risk_level = str(risk_level or "").strip().upper()
    if normalized_risk_level:
        if normalized_risk_level not in VALID_RISK_LEVELS:
            raise ValueError(f"不支持的风险等级：{risk_level}")
        stmt = stmt.where(HotspotEvent.risk_level == normalized_risk_level)
    normalized_keyword = str(keyword or "").strip()
    if normalized_keyword:
        pattern = f"%{normalized_keyword}%"
        stmt = stmt.where(
            or_(
                HotspotEventFeedback.event_key.like(pattern),
                HotspotEventFeedback.note.like(pattern),
                HotspotEvent.title.like(pattern),
            )
        )

    records: list[dict[str, Any]] = []
    for (
        feedback,
        event_title,
        event_category,
        event_heat_score,
        event_risk_level,
        event_source_count,
        event_credibility_score,
        event_credibility_level,
    ) in db.execute(stmt).all():
        item = feedback_to_dict(feedback)
        item.update(
            {
                "event_title": event_title,
                "event_category": event_category,
                "event_heat_score": event_heat_score,
                "event_risk_level": event_risk_level,
                "event_source_count": event_source_count,
                "event_credibility_score": event_credibility_score,
                "event_credibility_level": event_credibility_level,
            }
        )
        records.append(item)
    return records


def get_feedback_summary_map(db: Session, event_keys: list[str], *, created_by: str | None = None) -> dict[str, dict[str, Any]]:
    keys = [str(key).strip() for key in event_keys if str(key or "").strip()]
    if not keys:
        return {}

    stmt = (
        select(
            HotspotEventFeedback.event_key,
            HotspotEventFeedback.action,
            func.count(HotspotEventFeedback.id),
        )
        .where(HotspotEventFeedback.event_key.in_(keys))
        .group_by(HotspotEventFeedback.event_key, HotspotEventFeedback.action)
    )
    if created_by is not None:
        stmt = stmt.where(HotspotEventFeedback.created_by == created_by)
    rows = db.execute(stmt).all()
    summary: dict[str, dict[str, Any]] = {
        key: {
            "counts": {action: 0 for action in sorted(VALID_FEEDBACK_ACTIONS)},
            "positive_count": 0,
            "negative_count": 0,
            "is_favorite": False,
            "is_blocked": False,
            "score_adjustment": 0,
        }
        for key in keys
    }
    for event_key, action, count in rows:
        key = str(event_key)
        normalized_action = str(action).upper()
        item = summary.setdefault(
            key,
            {
                "counts": {action: 0 for action in sorted(VALID_FEEDBACK_ACTIONS)},
                "positive_count": 0,
                "negative_count": 0,
                "is_favorite": False,
                "is_blocked": False,
                "score_adjustment": 0,
            },
        )
        item["counts"][normalized_action] = int(count or 0)

    for item in summary.values():
        useful = int(item["counts"].get("USEFUL") or 0)
        favorite = int(item["counts"].get("FAVORITE") or 0)
        irrelevant = int(item["counts"].get("IRRELEVANT") or 0)
        blocked = int(item["counts"].get("BLOCK") or 0)
        item["positive_count"] = useful + favorite
        item["negative_count"] = irrelevant + blocked
        item["is_favorite"] = favorite > 0
        item["is_blocked"] = blocked > 0
        item["score_adjustment"] = min(12, useful * 3 + favorite * 5) - min(30, irrelevant * 8 + blocked * 20)
    return summary


def blocked_event_keys(db: Session, *, created_by: str | None = None) -> set[str]:
    stmt = (
        select(HotspotEventFeedback.event_key)
        .join(HotspotEvent, HotspotEvent.event_key == HotspotEventFeedback.event_key)
        .where(HotspotEventFeedback.action == BLOCK_ACTION)
    )
    if created_by is not None:
        stmt = stmt.where(HotspotEventFeedback.created_by == created_by)
    rows = db.execute(stmt).scalars()
    return {str(row) for row in rows if str(row or "").strip()}


def get_feedback_overview(db: Session, *, created_by: str | None = None) -> dict[str, Any]:
    stmt = (
        select(HotspotEventFeedback.action, func.count(HotspotEventFeedback.id))
        .join(HotspotEvent, HotspotEvent.event_key == HotspotEventFeedback.event_key)
        .group_by(HotspotEventFeedback.action)
    )
    if created_by is not None:
        stmt = stmt.where(HotspotEventFeedback.created_by == created_by)
    rows = db.execute(stmt).all()
    counts = {action: 0 for action in sorted(VALID_FEEDBACK_ACTIONS)}
    for action, count in rows:
        counts[str(action).upper()] = int(count or 0)
    return {
        "counts": counts,
        "positive_count": counts["USEFUL"] + counts["FAVORITE"],
        "negative_count": counts["IRRELEVANT"] + counts["BLOCK"],
        "blocked_count": counts["BLOCK"],
        "favorite_count": counts["FAVORITE"],
    }
