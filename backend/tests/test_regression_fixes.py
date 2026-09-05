from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.db.models import HotspotRawItem, KnowledgeChunk, KnowledgeDocument, KnowledgeIngestRun
from app.schemas import HotspotItem, HotspotEventDTO
from app.storage.repository import save_raw_items
from app.pipeline.scoring import _raw_heat_number, score_events
from app.connectors.arxiv_ai import ArxivAIConnector
from app.services import embedding_service
from app.services.knowledge_service import KnowledgeService


def test_default_suite_uses_disposable_services():
    assert engine.url.get_backend_name() == "sqlite"
    assert Path(engine.url.database).parent.name.startswith("hotspot-pytest-")
    from app.services.session_service import get_redis
    import fakeredis
    assert isinstance(get_redis(), fakeredis.FakeRedis)
    assert settings.redis_url == "redis://127.0.0.1:1/0"


def test_changed_observations_preserve_history_and_identical_retries_reuse():
    with SessionLocal() as db:
        old = HotspotItem(source="github", source_name="GitHub", source_item_id="snapshot-test",
                          title="AI project", url="https://github.com/test/snapshot",
                          rank=10, raw_hot_score="100", content="old", captured_at=datetime.utcnow())
        old_id = save_raw_items(db, [old])[0]
        new = old.model_copy(deep=True, update={"rank": 1, "raw_hot_score": "200", "content": "new"})
        new_id = save_raw_items(db, [new])[0]
        assert new_id != old_id
        assert db.get(HotspotRawItem, old_id).raw_hot_score == "100"
        assert db.get(HotspotRawItem, new_id).raw_hot_score == "200"
        new.raw_payload["_db_id"] = new_id
        assert save_raw_items(db, [new]) == [new_id]
        tomorrow = new.model_copy(deep=True, update={"captured_at": new.captured_at + timedelta(days=1)})
        assert save_raw_items(db, [tomorrow])[0] != new_id
        db.rollback()


def test_publication_time_never_adds_heat():
    for value in ("2026-09-05T12:00:00Z", "2026-09-05", "2026-09-05 12:00:00"):
        assert _raw_heat_number(value) == 0
    assert _raw_heat_number("2.5k") == 2500
    first = HotspotEventDTO(event_key="paper", title="AI paper", source_codes=["arxiv_ai"], source_count=1,
                           items=[HotspotItem(source="arxiv_ai", source_name="arXiv", title="AI paper", raw_hot_score="2026")])
    second = first.model_copy(deep=True)
    second.items[0].raw_hot_score = None
    assert score_events([first])[0].heat_score == score_events([second])[0].heat_score


def test_arxiv_keeps_publication_in_metadata_only():
    collector = ArxivAIConnector()
    collector.get_text = Mock(return_value='''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <title>AI paper</title><id>https://arxiv.org/abs/2609.00001</id>
      <published>2026-09-05T00:00:00Z</published></entry></feed>''')
    item = collector.fetch()[0]
    assert item.raw_hot_score is None
    assert item.raw_payload["published"] == "2026-09-05T00:00:00Z"


def remote_embeddings(monkeypatch):
    monkeypatch.setattr(embedding_service, "settings", SimpleNamespace(
        embedding_dimension=4, embedding_model="remote-model", embedding_base_url="https://example.test/v1",
        embedding_api_key="test", embedding_timeout_seconds=1))
    return embedding_service.EmbeddingService()


def test_remote_failure_never_returns_hash_vectors(monkeypatch):
    service = remote_embeddings(monkeypatch)
    service._embed_remote = Mock(side_effect=requests.ConnectionError("offline"))
    service._hashing_embedding = Mock()
    with pytest.raises(RuntimeError, match="vector space was not changed"):
        service.embed_texts(["same text"])
    service._hashing_embedding.assert_not_called()
    assert service.provider == "openai-compatible"
    assert service.model == "remote-model"
    service._embed_remote = Mock(return_value=[[1, 0, 0, 0]])
    assert service.embed_query("same text") == [1, 0, 0, 0]
    assert service.last_error is None


def test_query_failure_uses_keywords_not_incompatible_vectors(monkeypatch):
    service = KnowledgeService()
    service.embedding_service = remote_embeddings(monkeypatch)
    service.embedding_service._embed_remote = Mock(side_effect=requests.ConnectionError("offline"))
    service.qdrant.search = Mock()
    service._keyword_search = Mock(return_value=["keyword result"])
    with SessionLocal() as db:
        assert service.search(db, "database") == ["keyword result"]
    service.qdrant.search.assert_not_called()


def test_ingestion_failure_marks_failed_and_never_writes_hash_vectors(monkeypatch):
    service = KnowledgeService()
    service.embedding_service = remote_embeddings(monkeypatch)
    service.embedding_service._embed_remote = Mock(side_effect=requests.ConnectionError("offline"))
    service.qdrant = Mock()
    with SessionLocal() as db:
        run = KnowledgeIngestRun(status="RUNNING")
        db.add(run)
        db.commit()
        with pytest.raises(RuntimeError, match="vector space was not changed"):
            service.ingest_text_with_existing_run(db, run_id=run.id, title="failure-test", content="database system design test")
        db.refresh(run)
        assert run.status == "FAILED"
        assert db.get(KnowledgeDocument, run.document_id).status == "FAILED"
        service.qdrant.upsert_points.assert_not_called()


def test_embedding_space_mismatch_is_rejected():
    service = KnowledgeService()
    service.embedding_service.model = "new-model"
    service.embedding_service.dimension = 4
    with SessionLocal() as db:
        doc = KnowledgeDocument(title="space", content="database", content_hash="space-test")
        db.add(doc)
        db.flush()
        db.add(KnowledgeChunk(document_id=doc.id, chunk_index=0, content="database", content_hash="space-chunk",
                              vector_id="42", embedding_model="old-model", embedding_dim=4))
        db.flush()
        with pytest.raises(ValueError, match="Embedding space mismatch"):
            service._check_embedding_space(db)
        db.rollback()


@pytest.mark.parametrize("vectors", [[[1, 2], [3]], [[1, float("nan")], [1, 2]], [[], []]])
def test_invalid_remote_vectors_are_rejected(monkeypatch, vectors):
    service = remote_embeddings(monkeypatch)
    response = Mock()
    response.json.return_value = {"data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]}
    monkeypatch.setattr(requests, "post", Mock(return_value=response))
    with pytest.raises(RuntimeError):
        service.embed_texts(["first", "second"])
