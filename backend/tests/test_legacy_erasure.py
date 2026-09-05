"""Erasure tests use an isolated in-memory database, never the project DB."""
import importlib.util
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT
from app.db.session import Base
from app.db import models as m

spec = importlib.util.spec_from_file_location("purge", PROJECT_ROOT / "scripts/purge_legacy_data.py")
purge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(purge)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            m.HotspotRawItem(id=1, source_code="bilibili", title="legacy"),
            m.HotspotRawItem(id=2, source_code="hackernews", title="keep"),
            m.HotspotRawItem(id=3, source_code="github", title="old HTML", raw_payload={"source_url": "https://github.com/trending"}),
            m.HotspotRawItem(id=4, source_code="github", title="official", raw_payload={"source_url": "https://api.github.com/search/repositories"}),
            m.KnowledgeDocument(id=1, title="generated", source="daily_briefing:2026-07-05", content="old", content_hash="a"),
            m.KnowledgeDocument(id=2, title="manual", source="user-upload", content="keep", content_hash="b"),
        ])
        session.commit()
        yield session
    engine.dispose()


def test_erasure_preserves_official_records_and_manual_documents(db):
    selection = purge.plan(db)
    assert selection["raw_ids"] == [1, 3]
    vectors = Mock()
    purge.execute(db, selection, vectors)
    vectors.delete_by_document.assert_called_once_with(1)
    assert list(db.scalars(select(m.HotspotRawItem.id).order_by(m.HotspotRawItem.id))) == [2, 4]
    assert list(db.scalars(select(m.KnowledgeDocument.id))) == [2]
    assert purge.plan(db)["raw_ids"] == []
    assert purge.plan(db)["document_ids"] == []


def test_vector_failure_prevents_sql_erasure(db):
    vectors = Mock()
    vectors.delete_by_document.side_effect = RuntimeError("offline")
    with pytest.raises(RuntimeError, match="offline"):
        purge.execute(db, purge.plan(db), vectors)
    db.rollback()
    assert db.get(m.HotspotRawItem, 1) is not None
    assert db.get(m.KnowledgeDocument, 1) is not None
