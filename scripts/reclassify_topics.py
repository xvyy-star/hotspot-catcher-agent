"""Preview/apply topic-first categories to rule-generated events and archives."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select
from app.db.models import HotspotEvent, HotspotRawItem, DailyBriefing, KnowledgeDocument
from app.db.session import SessionLocal
from app.pipeline.analysis import classify_event
from app.pipeline.briefing import generate_markdown
from app.schemas import HotspotItem, HotspotEventDTO


def reclassify(db, apply=False):
    raw = {row.id: row for row in db.scalars(select(HotspotRawItem))}
    categories = {}
    changed = 0
    for row in db.scalars(select(HotspotEvent)):
        if row.analysis_mode not in {None, "", "RULE", "RULE_FALLBACK"}:
            continue
        items = [HotspotItem(
            source=raw[item_id].source_code, source_name=raw[item_id].source_name or raw[item_id].source_code,
            title=raw[item_id].title, content=raw[item_id].content,
            raw_payload=raw[item_id].raw_payload or {},
        ) for item_id in row.raw_item_ids or [] if item_id in raw]
        event = HotspotEventDTO(event_key=row.event_key, title=row.title, items=items,
                               source_codes=row.source_codes or [], source_count=row.source_count)
        category = classify_event(event)
        categories[row.event_key] = category
        changed += row.category != category
        if apply:
            row.category = category
    updated_briefings = 0
    for briefing in db.scalars(select(DailyBriefing)):
        data = deepcopy(briefing.raw_json or {})
        events = [HotspotEventDTO.model_validate(item) for item in data.get("events", [])]
        changed_snapshot = False
        for event in events:
            category = categories.get(event.event_key, event.category)
            changed_snapshot |= category != event.category
            event.category = category
        if changed_snapshot:
            updated_briefings += 1
            data["events"] = [event.model_dump(mode="json") for event in events]
            data["markdown"] = generate_markdown(events, briefing.briefing_date, data.get("source_health", {}))
            if apply:
                briefing.raw_json = data
                briefing.markdown = data["markdown"]
    if apply:
        db.commit()
        # Use the existing ingestion lifecycle; retry on the next run if indexing fails.
        from app.services.knowledge_service import KnowledgeService
        service = KnowledgeService()
        for briefing in db.scalars(select(DailyBriefing)):
            docs = list(db.scalars(select(KnowledgeDocument).where(
                KnowledgeDocument.source == f"daily_briefing:{briefing.briefing_date.isoformat()}")))
            if docs and any(doc.content != briefing.markdown for doc in docs):
                run = service.create_queued_run(db)
                service.ingest_briefing_with_existing_run(db, run_id=run["id"], briefing_date=briefing.briefing_date)
    return {"events_changed": changed, "briefings_changed": updated_briefings,
            "categories": dict(Counter(categories.values()))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        print(json.dumps(reclassify(db, args.apply), ensure_ascii=True, indent=2))
