"""Member responses derive only from public source evidence, never private RAG output."""

from __future__ import annotations

from datetime import date

from pydantic import ValidationError

from app.core.source_policy import OFFICIAL_SOURCE_CODES
from app.pipeline.analysis import fallback_analysis
from app.pipeline.briefing import build_briefing
from app.pipeline.evidence import has_real_evidence
from app.schemas import HotspotEventDTO, HotspotItem


def member_event(payload: dict) -> dict | None:
    items = []
    for raw in payload.get("items") or []:
        if not isinstance(raw, dict) or raw.get("source") not in OFFICIAL_SOURCE_CODES:
            continue
        # Do not copy opaque metadata: it can contain internal errors or context.
        data = {
            key: raw.get(key)
            for key in (
                "source",
                "title",
                "url",
                "source_item_id",
                "rank",
                "raw_hot_score",
                "content",
            )
        }
        data["source_name"] = raw.get("source_name") or raw["source"]
        if raw.get("captured_at"):
            data["captured_at"] = raw["captured_at"]
        try:
            item = HotspotItem.model_validate(data)
        except ValidationError:
            continue
        if has_real_evidence(item):
            items.append(item)
    if not items:
        return None
    sources = sorted({item.source for item in items})
    event = HotspotEventDTO(
        event_key=payload["event_key"],
        title=items[0].title,
        items=items,
        source_codes=sources,
        source_count=len(sources),
        heat_score=payload.get("heat_score") or 0,
    )
    # Existing summaries may have absorbed private context even without citation fields.
    event = fallback_analysis(event, "AI 与计算机技术")
    return {**event.model_dump(mode="json"), "has_real_evidence": True}


def member_briefing(payload: dict) -> dict:
    raw_json = payload.get("raw_json") or {}
    events = [
        view
        for item in raw_json.get("events", [])
        if isinstance(item, dict)
        for view in [member_event(item)]
        if view is not None
    ]
    day = payload["briefing_date"]
    if not isinstance(day, date):
        day = date.fromisoformat(day)
    briefing = build_briefing([HotspotEventDTO.model_validate(item) for item in events], day, {})
    data = briefing.model_dump(mode="json")
    return {
        "id": payload.get("id"),
        "briefing_date": data["briefing_date"],
        "title": data["title"],
        "summary": data["summary"],
        "markdown": data["markdown"],
        "status": data["status"],
        "raw_json": data,
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
    }
