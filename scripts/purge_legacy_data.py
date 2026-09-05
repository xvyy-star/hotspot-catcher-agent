"""Preview or execute the one-time official-source cutover with the server stopped.

Derived outputs cannot be reliably separated after mixed-source RAG analysis.
When legacy raw data exists, reset generated outputs, retaining official raw
records, manually imported documents, credentials and provider configuration.
Vector deletion precedes SQL commit and fails closed. Re-running is safe after
a partial vector deletion. No content backup is created for an erasure request.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import delete, select
from app.core.source_policy import OFFICIAL_SOURCE_CODES
from app.db import models as m
from app.db.session import SessionLocal
from app.services.qdrant_service import QdrantService


def legacy_raw(row):
    if row.source_code not in OFFICIAL_SOURCE_CODES:
        return True
    if row.source_code == "github":
        payload = row.raw_payload if isinstance(row.raw_payload, dict) else {}
        return payload.get("source_url") != "https://api.github.com/search/repositories"
    return False


GENERATED = (m.HotspotEventFeedback, m.HotspotEvent, m.DailyBriefing,
             m.LLMAnalysisCache, m.LLMCallLog, m.PushDeliveryLog, m.AgentRun)


def plan(db):
    raw = list(db.scalars(select(m.HotspotRawItem)))
    removed = [row for row in raw if legacy_raw(row)]
    reset = bool(removed)
    docs = [row for row in db.scalars(select(m.KnowledgeDocument))
            if reset and (row.source or "").startswith("daily_briefing:")]
    doc_ids = {row.id for row in docs}
    generated = {model.__tablename__: list(db.scalars(select(model.id))) if reset else []
                 for model in GENERATED}
    run_ids = {row.run_id for row in db.scalars(select(m.AgentRun))} if reset else set()
    log_ids = [row.id for row in db.scalars(select(m.SystemLog)) if reset and row.run_id in run_ids]
    return {"raw_ids": [row.id for row in removed],
            "removed_sources": dict(Counter(row.source_code for row in removed)),
            "retained_sources": dict(Counter(row.source_code for row in raw if not legacy_raw(row))),
            "document_ids": sorted(doc_ids), "generated": generated, "system_log_ids": log_ids,
            "source_ids": [row.id for row in db.scalars(select(m.HotspotSource))
                           if row.code not in OFFICIAL_SOURCE_CODES]}


def execute(db, selection, vectors):
    # Do not use KnowledgeService.delete_document: it swallows vector failures.
    for document_id in selection["document_ids"]:
        vectors.delete_by_document(document_id)
    if selection["document_ids"]:
        ids = selection["document_ids"]
        db.execute(delete(m.KnowledgeChunk).where(m.KnowledgeChunk.document_id.in_(ids)))
        db.execute(delete(m.KnowledgeIngestRun).where(m.KnowledgeIngestRun.document_id.in_(ids)))
        db.execute(delete(m.KnowledgeDocument).where(m.KnowledgeDocument.id.in_(ids)))
    for model in GENERATED:
        ids = selection["generated"][model.__tablename__]
        if ids:
            db.execute(delete(model).where(model.id.in_(ids)))
    for model, key in ((m.HotspotRawItem, "raw_ids"), (m.HotspotSource, "source_ids"),
                       (m.SystemLog, "system_log_ids")):
        if selection[key]:
            db.execute(delete(model).where(model.id.in_(selection[key])))
    db.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        selection = plan(db)
        summary = {key: len(value) if isinstance(value, list) else value
                   for key, value in selection.items() if key != "generated"}
        summary["generated"] = {key: len(value) for key, value in selection["generated"].items()}
        print(json.dumps(summary, ensure_ascii=True, indent=2))
        if args.apply:
            execute(db, selection, QdrantService())
            assert not plan(db)["raw_ids"], "Legacy raw records remain"
            print("COMPLETED: SQL committed; selected document vectors deleted.")


if __name__ == "__main__":
    main()
