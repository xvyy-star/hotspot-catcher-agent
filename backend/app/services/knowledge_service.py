"""知识库与 RAG 服务。"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterator

import requests
from sqlalchemy import delete, desc, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AIModelProvider, DailyBriefing, KnowledgeChunk, KnowledgeDocument, KnowledgeIngestRun
from app.services.chunk_service import split_text_into_chunks
from app.services.embedding_service import EmbeddingService
from app.services.knowledge_intent_router import KnowledgeIntentRouter
from app.services.model_provider_service import get_enabled_providers, provider_api_key
from app.services.qdrant_service import QdrantService

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeSearchResult:
    chunk_id: int
    document_id: int
    document_title: str
    chunk_index: int
    content: str
    score: float
    source: str | None = None
    metadata: dict[str, Any] | None = None


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def document_to_dict(doc: KnowledgeDocument, include_content: bool = False) -> dict[str, Any]:
    data = {
        "id": doc.id,
        "title": doc.title,
        "source": doc.source,
        "tags": doc.tags or [],
        "chunk_count": doc.chunk_count,
        "status": doc.status,
        "error_message": doc.error_message,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }
    if include_content:
        data["content"] = doc.content
    return data


def chunk_to_dict(chunk: KnowledgeChunk) -> dict[str, Any]:
    return {
        "id": chunk.id,
        "document_id": chunk.document_id,
        "chunk_index": chunk.chunk_index,
        "title": chunk.title,
        "content": chunk.content,
        "token_count": chunk.token_count,
        "vector_id": chunk.vector_id,
        "embedding_model": chunk.embedding_model,
        "embedding_dim": chunk.embedding_dim,
        "metadata": chunk.metadata_json or {},
        "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
    }


def ingest_run_to_dict(run: KnowledgeIngestRun, doc: KnowledgeDocument | None = None) -> dict[str, Any]:
    """知识库导入任务序列化。

    交付说明：
    企业级导入不能只返回“成功/失败”，还要能追踪失败原因、耗时、chunk 数和向量库集合，
    这样运维和产品都能知道卡在解析、切分、embedding 还是向量入库阶段。
    """
    duration_ms: int | None = None
    if run.started_at and run.finished_at:
        duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
    return {
        "id": run.id,
        "document_id": run.document_id,
        "document_title": doc.title if doc else None,
        "document_source": doc.source if doc else None,
        "status": run.status,
        "chunk_count": run.chunk_count,
        "embedding_model": run.embedding_model,
        "vector_collection": run.vector_collection,
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_ms": duration_ms,
    }


class KnowledgeService:
    """知识库业务服务。"""

    def __init__(self) -> None:
        self.embedding_service = EmbeddingService()
        self.qdrant = QdrantService()

    def create_document(
        self,
        db: Session,
        *,
        title: str,
        content: str,
        source: str | None = None,
        tags: list[str] | None = None,
        chunk_size: int = 700,
        overlap: int = 100,
    ) -> dict[str, Any]:
        """同步创建知识库文档。

        同步接口仍保留，便于简单本地演示；内部复用“带 run 状态”的核心导入逻辑。
        """
        run = KnowledgeIngestRun(status="RUNNING", vector_collection=settings.qdrant_collection)
        db.add(run)
        db.flush()
        return self.ingest_text_with_existing_run(
            db,
            run_id=int(run.id),
            title=title,
            content=content,
            source=source,
            tags=tags,
            chunk_size=chunk_size,
            overlap=overlap,
        )

    def create_queued_run(self, db: Session, *, status: str = "QUEUED") -> dict[str, Any]:
        """创建一个待执行导入任务。

        异步导入接口先返回这个 run_id，后台任务再不断更新状态。
        """
        run = KnowledgeIngestRun(status=status, vector_collection=settings.qdrant_collection)
        db.add(run)
        db.commit()
        db.refresh(run)
        return ingest_run_to_dict(run)

    def update_ingest_run_status(
        self,
        db: Session,
        run_id: int,
        status: str,
        *,
        error_message: str | None = None,
        finished: bool = False,
    ) -> dict[str, Any] | None:
        """更新导入任务状态。"""
        run = db.get(KnowledgeIngestRun, run_id)
        if not run:
            return None
        run.status = status
        if error_message is not None:
            run.error_message = error_message
        if finished:
            run.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
        doc = db.get(KnowledgeDocument, run.document_id) if run.document_id else None
        return ingest_run_to_dict(run, doc)

    def reindex_vectors_with_existing_run(
        self,
        db: Session,
        *,
        run_id: int,
        document_id: int | None = None,
        batch_size: int = 16,
        recreate_collection: bool = False,
    ) -> dict[str, Any]:
        """用当前 Embedding 配置重建 Qdrant 向量。

        使用场景：
        - 从本地 hashing embedding 切换到真实 embedding API。
        - 更换 embedding 模型或维度。
        - Qdrant collection 丢失，需要从 MySQL chunk 元数据恢复向量。
        """
        run = db.get(KnowledgeIngestRun, run_id)
        if not run:
            raise ValueError(f"导入任务不存在：{run_id}")
        if recreate_collection and document_id is not None:
            raise ValueError("重建整个 collection 时不能只选择单个文档")
        run.status = "EMBEDDING"
        run.error_message = None
        if document_id:
            run.document_id = document_id
        db.commit()

        stmt = (
            select(KnowledgeChunk)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(KnowledgeDocument.status == "ACTIVE")
            .order_by(KnowledgeChunk.id.asc())
        )
        if document_id:
            stmt = stmt.where(KnowledgeChunk.document_id == document_id)
        chunks = list(db.execute(stmt).scalars())
        if not chunks:
            raise ValueError("暂无可重建的知识库 chunk")

        batch_size = max(1, min(int(batch_size or 16), 64))
        try:
            # 先探测真实维度，再决定创建或校验 Qdrant collection。
            first_vector = self.embedding_service.embed_query(chunks[0].content)
            vector_size = len(first_vector)
            if document_id is not None:
                self._check_embedding_space(db)
            if recreate_collection:
                self.qdrant.recreate_collection(vector_size)
            else:
                self.qdrant.ensure_collection(vector_size)

            total = 0
            for start in range(0, len(chunks), batch_size):
                batch = chunks[start : start + batch_size]
                texts = [row.content for row in batch]
                vectors = [first_vector] + self.embedding_service.embed_texts(texts[1:]) if start == 0 else self.embedding_service.embed_texts(texts)

                run = db.get(KnowledgeIngestRun, run_id)
                if run:
                    run.status = "VECTOR_UPSERT"
                    run.chunk_count = total
                    db.commit()

                points: list[dict[str, Any]] = []
                for row, vector in zip(batch, vectors):
                    doc = db.get(KnowledgeDocument, row.document_id)
                    row.vector_id = str(row.id)
                    row.embedding_model = self.embedding_service.model
                    row.embedding_dim = len(vector)
                    points.append(
                        {
                            "id": int(row.id),
                            "vector": vector,
                            "payload": {
                                "chunk_id": int(row.id),
                                "document_id": int(row.document_id),
                                "document_title": doc.title if doc else row.title,
                                "chunk_index": int(row.chunk_index),
                                "source": doc.source if doc else None,
                                "tags": doc.tags if doc else [],
                                "content_preview": row.content[:300],
                            },
                        }
                    )
                self.qdrant.upsert_points(points)
                total += len(batch)
                run = db.get(KnowledgeIngestRun, run_id)
                if run:
                    run.chunk_count = total
                    run.embedding_model = self.embedding_service.model
                    run.vector_collection = settings.qdrant_collection
                db.commit()

            run = db.get(KnowledgeIngestRun, run_id)
            if not run:
                raise ValueError("重建向量任务记录异常")
            run.status = "SUCCESS"
            run.chunk_count = total
            run.embedding_model = self.embedding_service.model
            run.vector_collection = settings.qdrant_collection
            run.finished_at = datetime.utcnow()
            db.commit()
            doc = db.get(KnowledgeDocument, run.document_id) if run.document_id else None
            return {
                "run": ingest_run_to_dict(run, doc),
                "chunk_count": total,
                "embedding_model": self.embedding_service.model,
                "embedding_provider": self.embedding_service.provider,
                "embedding_dim": vector_size,
                "vector_collection": settings.qdrant_collection,
                "recreate_collection": recreate_collection,
            }
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            run = db.get(KnowledgeIngestRun, run_id)
            if run:
                run.status = "FAILED"
                run.error_message = str(exc)
                run.finished_at = datetime.utcnow()
            db.commit()
            logger.exception("知识库向量重建失败")
            raise

    def reindex_vectors(
        self,
        db: Session,
        *,
        document_id: int | None = None,
        batch_size: int = 16,
        recreate_collection: bool = False,
    ) -> dict[str, Any]:
        """同步重建向量，主要用于脚本或小数据量本地演示。"""
        run = KnowledgeIngestRun(
            status="RUNNING",
            document_id=document_id,
            vector_collection=settings.qdrant_collection,
        )
        db.add(run)
        db.flush()
        return self.reindex_vectors_with_existing_run(
            db,
            run_id=int(run.id),
            document_id=document_id,
            batch_size=batch_size,
            recreate_collection=recreate_collection,
        )

    def ingest_text_with_existing_run(
        self,
        db: Session,
        *,
        run_id: int,
        title: str,
        content: str,
        source: str | None = None,
        tags: list[str] | None = None,
        chunk_size: int = 700,
        overlap: int = 100,
    ) -> dict[str, Any]:
        """使用已有 run_id 导入文本。

        状态流转：
        CHUNKING -> EMBEDDING -> VECTOR_UPSERT -> SUCCESS
        异常时写入 FAILED，并尽量保留 document_id，便于前端定位。
        """
        run = db.get(KnowledgeIngestRun, run_id)
        if not run:
            raise ValueError(f"导入任务不存在：{run_id}")

        title = (title or "").strip()
        content = (content or "").strip()
        if not title:
            raise ValueError("文档标题不能为空")
        if len(content) < 10:
            raise ValueError("文档内容太短，至少需要 10 个字符")

        doc = KnowledgeDocument(
            title=title,
            source=source,
            content=content,
            content_hash=sha256_text(content),
            tags=tags or [],
            status="INGESTING",
        )
        db.add(doc)
        db.flush()
        run.document_id = doc.id
        run.status = "CHUNKING"
        run.error_message = None
        db.commit()

        try:
            chunks = split_text_into_chunks(content, chunk_size=chunk_size, overlap=overlap)
            if not chunks:
                raise ValueError("文档无法切分出有效 chunk")

            chunk_rows: list[KnowledgeChunk] = []
            for idx, chunk_text in enumerate(chunks):
                row = KnowledgeChunk(
                    document_id=doc.id,
                    chunk_index=idx,
                    title=title,
                    content=chunk_text,
                    content_hash=sha256_text(chunk_text),
                    token_count=len(chunk_text),
                    metadata_json={"source": source, "tags": tags or []},
                )
                db.add(row)
                chunk_rows.append(row)
            db.flush()
            db.commit()

            run = db.get(KnowledgeIngestRun, run_id)
            if run:
                run.status = "EMBEDDING"
                db.commit()
            vectors = self.embedding_service.embed_texts([row.content for row in chunk_rows])
            vector_size = len(vectors[0]) if vectors else settings.embedding_dimension
            self._check_embedding_space(db)
            self.qdrant.ensure_collection(vector_size)

            run = db.get(KnowledgeIngestRun, run_id)
            if run:
                run.status = "VECTOR_UPSERT"
                db.commit()
            points: list[dict[str, Any]] = []
            for row, vector in zip(chunk_rows, vectors):
                row.vector_id = str(row.id)
                row.embedding_model = self.embedding_service.model
                row.embedding_dim = len(vector)
                points.append(
                    {
                        "id": int(row.id),
                        "vector": vector,
                        "payload": {
                            "chunk_id": int(row.id),
                            "document_id": int(doc.id),
                            "document_title": doc.title,
                            "chunk_index": int(row.chunk_index),
                            "source": source,
                            "tags": tags or [],
                            "content_preview": row.content[:300],
                        },
                    }
                )
            self.qdrant.upsert_points(points)

            run = db.get(KnowledgeIngestRun, run_id)
            doc = db.get(KnowledgeDocument, doc.id)
            if not run or not doc:
                raise ValueError("导入任务或文档记录异常")
            doc.chunk_count = len(chunk_rows)
            doc.status = "ACTIVE"
            doc.error_message = None
            run.status = "SUCCESS"
            run.chunk_count = len(chunk_rows)
            run.embedding_model = self.embedding_service.model
            run.finished_at = datetime.utcnow()
            db.commit()
            return {"document": document_to_dict(doc, include_content=True), "chunks": [chunk_to_dict(row) for row in chunk_rows], "run_id": run.id}
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            try:
                self.qdrant.delete_by_document(int(doc.id))
            except Exception:  # noqa: BLE001
                logger.warning("清理失败文档的 Qdrant 向量失败 document_id=%s", doc.id, exc_info=True)
            run = db.get(KnowledgeIngestRun, run_id)
            if run:
                run.status = "FAILED"
                run.error_message = str(exc)
                run.finished_at = datetime.utcnow()
            failed_doc = db.get(KnowledgeDocument, getattr(doc, "id", None)) if getattr(doc, "id", None) else None
            if failed_doc:
                failed_doc.status = "FAILED"
                failed_doc.error_message = str(exc)
            db.commit()
            logger.exception("知识库文档导入失败")
            raise

    def list_documents(self, db: Session, limit: int = 50) -> list[dict[str, Any]]:
        rows = db.execute(select(KnowledgeDocument).order_by(desc(KnowledgeDocument.created_at)).limit(limit)).scalars()
        return [document_to_dict(row) for row in rows]

    def list_ingest_runs(
        self,
        db: Session,
        *,
        limit: int = 50,
        status: str | None = None,
        document_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """查询知识库导入任务列表。"""
        stmt = select(KnowledgeIngestRun).order_by(desc(KnowledgeIngestRun.started_at)).limit(limit)
        if status:
            stmt = stmt.where(KnowledgeIngestRun.status == status.upper())
        if document_id:
            stmt = stmt.where(KnowledgeIngestRun.document_id == document_id)
        rows = db.execute(stmt).scalars().all()
        doc_ids = [int(row.document_id) for row in rows if row.document_id]
        docs = {}
        if doc_ids:
            doc_rows = db.execute(select(KnowledgeDocument).where(KnowledgeDocument.id.in_(doc_ids))).scalars().all()
            docs = {int(doc.id): doc for doc in doc_rows}
        return [ingest_run_to_dict(row, docs.get(int(row.document_id or 0))) for row in rows]

    def get_ingest_run(self, db: Session, run_id: int) -> dict[str, Any] | None:
        """查询单个知识库导入任务。"""
        run = db.get(KnowledgeIngestRun, run_id)
        if not run:
            return None
        doc = db.get(KnowledgeDocument, run.document_id) if run.document_id else None
        return ingest_run_to_dict(run, doc)

    def _get_briefing_for_ingest(self, db: Session, briefing_date: date | None = None) -> DailyBriefing | None:
        """找到要写入知识库的早报。

        briefing_date 为空时取最新一份早报；传入日期时精确取当天早报。
        这样定时任务、历史补录、手动触发都能复用同一套逻辑。
        """
        if briefing_date:
            return db.execute(select(DailyBriefing).where(DailyBriefing.briefing_date == briefing_date)).scalar_one_or_none()
        # 先只查 id，避免 MySQL 排序时把 markdown/raw_json 大字段一起放入 sort buffer。
        latest_id = db.execute(
            select(DailyBriefing.id).order_by(desc(DailyBriefing.briefing_date)).limit(1)
        ).scalar_one_or_none()
        return db.get(DailyBriefing, latest_id) if latest_id else None

    def ingest_briefing_with_existing_run(
        self,
        db: Session,
        *,
        run_id: int,
        briefing_date: date | None = None,
        chunk_size: int = 800,
        overlap: int = 120,
    ) -> dict[str, Any]:
        """使用已有 run_id 把每日早报写入知识库。

        企业项目里“历史热点记忆”必须幂等：
        - 同一天同内容重复执行时，不重复创建向量和文档。
        - 同一天早报被重新生成且内容变化时，删除旧版本向量后写入新版。
        """
        run = db.get(KnowledgeIngestRun, run_id)
        if not run:
            raise ValueError(f"导入任务不存在：{run_id}")

        run.status = "PARSING"
        run.error_message = None
        db.commit()

        briefing = self._get_briefing_for_ingest(db, briefing_date)
        if not briefing or not briefing.markdown:
            run.status = "FAILED"
            run.error_message = "暂无可导入的早报"
            run.finished_at = datetime.utcnow()
            db.commit()
            raise ValueError("暂无可导入的早报")

        day_text = briefing.briefing_date.isoformat()
        source = f"daily_briefing:{day_text}"
        title = f"历史早报｜{day_text}"
        content_hash = sha256_text(briefing.markdown)

        candidates = list(
            db.execute(
                select(KnowledgeDocument)
                .where(
                    or_(
                        KnowledgeDocument.source == source,
                        KnowledgeDocument.source == "daily_briefing",
                        KnowledgeDocument.title == title,
                    )
                )
                .order_by(desc(KnowledgeDocument.created_at))
            ).scalars()
        )
        same_content_docs = [doc for doc in candidates if doc.content_hash == content_hash and doc.status == "ACTIVE"]
        existing = next((doc for doc in same_content_docs if doc.source == source), None) or (same_content_docs[0] if same_content_docs else None)
        if existing:
            if existing.source != source:
                # 兼容旧版本 source="daily_briefing" 的历史数据，迁移成按日期可追溯的 source。
                existing.source = source
                db.commit()
            for duplicate in candidates:
                if duplicate.id != existing.id:
                    self.delete_document(db, int(duplicate.id))
            existing = db.get(KnowledgeDocument, int(existing.id))
            if not existing:
                raise ValueError("历史早报文档去重后记录异常")
            chunks = list(
                db.execute(
                    select(KnowledgeChunk)
                    .where(KnowledgeChunk.document_id == existing.id)
                    .order_by(KnowledgeChunk.chunk_index.asc())
                ).scalars()
            )
            run.document_id = existing.id
            run.status = "SUCCESS"
            run.chunk_count = existing.chunk_count
            run.embedding_model = chunks[0].embedding_model if chunks else self.embedding_service.model
            run.vector_collection = settings.qdrant_collection
            run.finished_at = datetime.utcnow()
            db.commit()
            return {
                "document": document_to_dict(existing, include_content=True),
                "chunks": [chunk_to_dict(chunk) for chunk in chunks],
                "run_id": run.id,
                "skipped_duplicate": True,
            }

        for old_doc in candidates:
            # 同一天早报内容变化时，先删除旧向量和旧文档，再写入新版本，避免 RAG 检索到过期早报。
            self.delete_document(db, int(old_doc.id))

        return self.ingest_text_with_existing_run(
            db,
            run_id=run_id,
            title=title,
            content=briefing.markdown,
            source=source,
            tags=["历史早报", "热点记忆", "自动入库", day_text],
            chunk_size=chunk_size,
            overlap=overlap,
        )

    def get_document(self, db: Session, document_id: int) -> dict[str, Any] | None:
        doc = db.get(KnowledgeDocument, document_id)
        if not doc:
            return None
        chunks = db.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id).order_by(KnowledgeChunk.chunk_index.asc())
        ).scalars()
        return {"document": document_to_dict(doc, include_content=True), "chunks": [chunk_to_dict(chunk) for chunk in chunks]}

    def delete_document(self, db: Session, document_id: int) -> bool:
        doc = db.get(KnowledgeDocument, document_id)
        if not doc:
            return False
        try:
            self.qdrant.delete_by_document(document_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("删除 Qdrant 文档向量失败，继续删除 MySQL 元数据: %s", exc)
        db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))
        db.delete(doc)
        db.commit()
        return True

    def search(
        self,
        db: Session,
        query: str,
        top_k: int = 5,
        document_ids: list[int] | None = None,
    ) -> list[KnowledgeSearchResult]:
        query = (query or "").strip()
        if not query:
            raise ValueError("检索问题不能为空")
        top_k = max(1, min(int(top_k or 5), 20))
        allowed_document_ids = self._normalize_document_ids(document_ids)
        try:
            vector = self.embedding_service.embed_query(query)
            self._check_embedding_space(db)
            hits = self.qdrant.search(vector, limit=top_k, document_ids=allowed_document_ids)
            results = self._hydrate_qdrant_hits(db, hits, allowed_document_ids)
            if results:
                return results
        except Exception as exc:  # noqa: BLE001
            logger.warning("Qdrant 检索失败，降级 MySQL 关键词检索: %s", exc)
        return self._keyword_search(db, query, top_k, allowed_document_ids)

    def _check_embedding_space(self, db: Session) -> None:
        spaces = db.execute(select(KnowledgeChunk.embedding_model, KnowledgeChunk.embedding_dim)
                            .where(KnowledgeChunk.vector_id.is_not(None)).distinct()).all()
        expected = (self.embedding_service.model, self.embedding_service.dimension)
        if any(tuple(space) != expected for space in spaces):
            raise ValueError("Embedding space mismatch; rebuild the complete vector index before use")

    @staticmethod
    def _normalize_document_ids(document_ids: list[int] | None) -> list[int] | None:
        if not document_ids:
            return None
        normalized = sorted({int(item) for item in document_ids if int(item) > 0})
        return normalized or None

    def _hydrate_qdrant_hits(
        self,
        db: Session,
        hits: list[dict[str, Any]],
        document_ids: list[int] | None = None,
    ) -> list[KnowledgeSearchResult]:
        results: list[KnowledgeSearchResult] = []
        allowed_document_ids = set(document_ids or [])
        for hit in hits:
            payload = hit.get("payload") or {}
            chunk_id = payload.get("chunk_id") or hit.get("id")
            if not chunk_id:
                continue
            chunk = db.get(KnowledgeChunk, int(chunk_id))
            if not chunk:
                continue
            if allowed_document_ids and int(chunk.document_id) not in allowed_document_ids:
                continue
            doc = db.get(KnowledgeDocument, chunk.document_id)
            if not doc or doc.status != "ACTIVE":
                continue
            results.append(
                KnowledgeSearchResult(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    document_title=doc.title if doc else (chunk.title or "未知文档"),
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    score=float(hit.get("score") or 0),
                    source=doc.source if doc else None,
                    metadata=chunk.metadata_json or {},
                )
            )
        return results

    def _keyword_search(
        self,
        db: Session,
        query: str,
        top_k: int,
        document_ids: list[int] | None = None,
    ) -> list[KnowledgeSearchResult]:
        keywords = [part.lower() for part in query.replace("/", " ").replace("，", " ").split() if part.strip()]
        stmt = select(KnowledgeChunk).order_by(desc(KnowledgeChunk.created_at)).limit(500)
        if document_ids:
            stmt = stmt.where(KnowledgeChunk.document_id.in_(document_ids))
        chunks = db.execute(stmt).scalars()
        scored: list[tuple[float, KnowledgeChunk, KnowledgeDocument | None]] = []
        for chunk in chunks:
            text = chunk.content.lower()
            score = sum(text.count(keyword) for keyword in keywords) if keywords else 0
            if query.lower() in text:
                score += 3
            if score <= 0:
                continue
            doc = db.get(KnowledgeDocument, chunk.document_id)
            if not doc or doc.status != "ACTIVE":
                continue
            scored.append((float(score), chunk, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            KnowledgeSearchResult(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_title=doc.title if doc else (chunk.title or "未知文档"),
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                score=score,
                source=doc.source if doc else None,
                metadata=chunk.metadata_json or {},
            )
            for score, chunk, doc in scored[:top_k]
        ]

    def ask(
        self,
        db: Session,
        question: str,
        top_k: int = 5,
        document_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        routed = KnowledgeIntentRouter.route(question)
        if routed.route == "DIRECT_REPLY":
            return {
                "question": question,
                "document_ids": self._normalize_document_ids(document_ids) or [],
                "answer": routed.answer or "",
                "mode": "DIRECT_REPLY",
                "model": None,
                "error": None,
                "references": [],
                "skipped_retrieval": True,
                "intent": routed.intent,
                "route_reason": routed.reason,
                "latest_question": routed.latest_question,
            }

        results = self.search(db, question, top_k=top_k, document_ids=document_ids)
        answer, model, mode, error = self._generate_answer(db, question, results)
        return {
            "question": question,
            "document_ids": self._normalize_document_ids(document_ids) or [],
            "answer": answer,
            "mode": mode,
            "model": model,
            "error": error,
            "references": [self.search_result_to_dict(item) for item in results],
            "skipped_retrieval": False,
            "intent": routed.intent,
            "route_reason": routed.reason,
            "latest_question": routed.latest_question,
        }

    def ask_stream(
        self,
        db: Session,
        question: str,
        top_k: int = 5,
        document_ids: list[int] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """流式知识问答事件。

        返回 NDJSON 事件：
        - meta：模式、模型、引用、路由原因
        - delta：增量文本
        - done：结束
        """
        routed = KnowledgeIntentRouter.route(question)
        normalized_doc_ids = self._normalize_document_ids(document_ids) or []

        if routed.route == "DIRECT_REPLY":
            yield {
                "type": "meta",
                "mode": "DIRECT_REPLY",
                "model": None,
                "references": [],
                "skipped_retrieval": True,
                "intent": routed.intent,
                "route_reason": routed.reason,
                "latest_question": routed.latest_question,
                "document_ids": normalized_doc_ids,
            }
            for chunk in self._text_chunks(routed.answer or "", size=1, delay_seconds=0.012):
                yield {"type": "delta", "content": chunk}
            yield {"type": "done"}
            return

        results = self.search(db, question, top_k=top_k, document_ids=document_ids)
        references = [self.search_result_to_dict(item) for item in results]
        if not results:
            yield {
                "type": "meta",
                "mode": "NO_CONTEXT",
                "model": None,
                "references": [],
                "skipped_retrieval": False,
                "intent": routed.intent,
                "route_reason": routed.reason,
                "latest_question": routed.latest_question,
                "document_ids": normalized_doc_ids,
            }
            for chunk in self._text_chunks("知识库里暂时没有检索到相关内容。", size=1, delay_seconds=0.012):
                yield {"type": "delta", "content": chunk}
            yield {"type": "done"}
            return

        prompt = self._build_rag_prompt(question, results)
        last_error: str | None = None
        for provider in get_enabled_providers(db):
            try:
                stream_iter = self._call_chat_stream(provider, prompt)
                first_delta = next(stream_iter, "")
                if not first_delta:
                    continue
                yield {
                    "type": "meta",
                    "mode": "LLM_RAG",
                    "model": provider.model,
                    "references": references,
                    "skipped_retrieval": False,
                    "intent": routed.intent,
                    "route_reason": routed.reason,
                    "latest_question": routed.latest_question,
                    "document_ids": normalized_doc_ids,
                }
                yield {"type": "delta", "content": first_delta}
                for delta in stream_iter:
                    if delta:
                        yield {"type": "delta", "content": delta}
                yield {"type": "done"}
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("RAG LLM 流式回答失败 provider=%s: %s", provider.code, exc)
                last_error = str(exc)

        fallback = self._fallback_answer(question, results)
        yield {
            "type": "meta",
            "mode": "RULE_RAG",
            "model": None,
            "references": references,
            "skipped_retrieval": False,
            "intent": routed.intent,
            "route_reason": routed.reason,
            "latest_question": routed.latest_question,
            "document_ids": normalized_doc_ids,
            "error": last_error,
        }
        for chunk in self._text_chunks(fallback, size=8, delay_seconds=0.006):
            yield {"type": "delta", "content": chunk}
        yield {"type": "done"}

    @classmethod
    def _build_direct_reply(cls, question: str) -> dict[str, str] | None:
        """Directly answer chatty/help inputs without RAG retrieval."""
        latest = cls._extract_latest_question(question)
        compact = cls._compact_intent_text(latest)
        if not compact:
            return None

        greetings = {
            "你好", "您好", "哈喽", "哈啰", "嗨", "在吗", "在不在",
            "早", "早上好", "上午好", "中午好", "下午好", "晚上好",
            "hi", "hello", "hey", "hellohello",
        }
        thanks = {"谢谢", "谢谢你", "感谢", "感谢你", "多谢", "辛苦了", "thx", "thanks", "thankyou"}
        byes = {"再见", "拜拜", "回头见", "先这样", "bye", "goodbye", "seeyou"}
        help_intents = {"帮助", "使用说明", "怎么用", "如何使用", "你能做什么", "能做什么", "你会什么"}
        identity_intents = {
            "你是谁", "你到底是谁", "你叫什么", "你是啥", "你是什么",
            "你是干嘛的", "你是做什么的", "你是机器人吗", "你是ai吗",
            "介绍一下你", "自我介绍",
        }

        if compact in greetings:
            return {
                "intent": "GREETING",
                "answer": "你好！我是热点捕手的知识问答助手。寒暄不会检索知识库；需要查资料时，请直接问具体问题。",
            }
        if compact in thanks:
            return {
                "intent": "THANKS",
                "answer": "不客气！需要查知识库时，直接问具体问题就行。",
            }
        if compact in byes:
            return {
                "intent": "BYE",
                "answer": "好的，后面需要继续分析热点或查询知识库时再叫我。",
            }
        if compact in help_intents:
            return {
                "intent": "HELP",
                "answer": "我可以做两类事：1）普通寒暄直接回复，不检索知识库；2）具体业务或资料问题才检索文档并给出引用。",
            }
        if compact in identity_intents or any(item in compact for item in identity_intents):
            return {
                "intent": "IDENTITY",
                "answer": "我是热点捕手的知识问答助手，负责回答知识库和热点情报相关问题。身份、寒暄这类问题我会直接回复，不检索知识库。",
            }
        return None

    @staticmethod
    def _extract_latest_question(question: str) -> str:
        text = (question or "").strip()
        for marker in ("用户新问题：", "用户新问题:", "新问题：", "新问题:"):
            if marker in text:
                return text.rsplit(marker, 1)[-1].strip()
        return text

    @staticmethod
    def _compact_intent_text(text: str) -> str:
        lowered = (text or "").strip().lower()
        punctuation = set(" \t\r\n,.;:!?~()[]{}<>\"'`_-")
        punctuation.update("，。！？～、；：（）【】《》“”‘’·…—")
        return "".join(ch for ch in lowered if ch not in punctuation)

    def _generate_answer(self, db: Session, question: str, results: list[KnowledgeSearchResult]) -> tuple[str, str | None, str, str | None]:
        context = "\n\n".join(
            f"[引用 {idx}] 文档：{item.document_title}｜chunk#{item.chunk_index}\n{item.content}"
            for idx, item in enumerate(results, start=1)
        )
        if not results:
            return "知识库里暂时没有检索到相关内容。", None, "NO_CONTEXT", None

        prompt = (
            "你是热点捕手 Agent 的知识库问答助手。请只基于给定引用回答，必须用中文，"
            "结尾列出引用编号。如果材料不足，就说明不足。\n\n"
            f"用户问题：{question}\n\n知识库引用：\n{context}"
        )
        providers = get_enabled_providers(db)
        for provider in providers:
            try:
                answer = self._call_chat(provider, prompt)
                if answer:
                    return answer, provider.model, "LLM_RAG", None
            except Exception as exc:  # noqa: BLE001
                logger.warning("RAG LLM 回答失败 provider=%s: %s", provider.code, exc)
                last_error = str(exc)
        fallback = self._fallback_answer(question, results)
        return fallback, None, "RULE_RAG", locals().get("last_error")

    @staticmethod
    def _call_chat(provider: AIModelProvider, prompt: str) -> str:
        url = f"{provider.base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        api_key = provider_api_key(provider)
        if provider.requires_api_key and not api_key:
            raise RuntimeError(f"Provider {provider.code} 未配置 API Key")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": "你是严谨的企业知识库 RAG 助手。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": min(provider.temperature or 0.2, 0.5),
            "max_tokens": provider.max_tokens or 800,
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=provider.timeout_seconds or 60)
        resp.raise_for_status()
        data = resp.json()
        return ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

    @staticmethod
    def _build_rag_prompt(question: str, results: list[KnowledgeSearchResult]) -> str:
        context = "\n\n".join(
            f"[引用 {idx}] 文档：{item.document_title}｜chunk#{item.chunk_index}\n{item.content}"
            for idx, item in enumerate(results, start=1)
        )
        return (
            "你是热点捕手 Agent 的知识库问答助手。请只基于给定引用回答，必须用中文，"
            "结尾列出引用编号。如果材料不足，就说明不足。\n\n"
            f"用户问题：{question}\n\n知识库引用：\n{context}"
        )

    @staticmethod
    def _call_chat_stream(provider: AIModelProvider, prompt: str) -> Iterator[str]:
        url = f"{provider.base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        api_key = provider_api_key(provider)
        if provider.requires_api_key and not api_key:
            raise RuntimeError(f"Provider {provider.code} 未配置 API Key")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": provider.model,
            "messages": [
                {"role": "system", "content": "你是严谨的企业知识库 RAG 助手。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": min(provider.temperature or 0.2, 0.5),
            "max_tokens": provider.max_tokens or 800,
            "stream": True,
        }
        with requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=provider.timeout_seconds or 60,
            stream=True,
        ) as resp:
            resp.raise_for_status()
            for raw_line in resp.iter_lines(decode_unicode=False):
                if not raw_line:
                    continue
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data_text = line.removeprefix("data:").strip()
                if data_text == "[DONE]":
                    break
                try:
                    data = json.loads(data_text)
                except json.JSONDecodeError:
                    continue
                choice = (data.get("choices") or [{}])[0]
                delta = (choice.get("delta") or {}).get("content") or ""
                if delta:
                    yield delta

    @staticmethod
    def _text_chunks(text: str, *, size: int = 1, delay_seconds: float = 0) -> Iterator[str]:
        step = max(size, 1)
        for idx in range(0, len(text or ""), step):
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            yield text[idx : idx + step]

    @staticmethod
    def _fallback_answer(question: str, results: list[KnowledgeSearchResult]) -> str:
        lines = [f"围绕问题“{question}”，知识库检索到 {len(results)} 条相关材料："]
        for idx, item in enumerate(results, start=1):
            preview = item.content[:180].replace("\n", " ")
            lines.append(f"{idx}. {item.document_title}：{preview}……")
        lines.append("\n建议：基于上述材料继续追问更具体的问题，或补充更多业务资料提升回答质量。")
        return "\n".join(lines)

    @staticmethod
    def search_result_to_dict(item: KnowledgeSearchResult) -> dict[str, Any]:
        return {
            "chunk_id": item.chunk_id,
            "document_id": item.document_id,
            "document_title": item.document_title,
            "chunk_index": item.chunk_index,
            "content": item.content,
            "score": round(item.score, 4),
            "source": item.source,
            "metadata": item.metadata or {},
        }

    def ingest_today_briefing(self, db: Session) -> dict[str, Any]:
        """同步把最新一份早报写入知识库。

        保留同步接口给本地演示使用；内部同样走幂等写入逻辑。
        """
        run = KnowledgeIngestRun(status="RUNNING", vector_collection=settings.qdrant_collection)
        db.add(run)
        db.flush()
        return self.ingest_briefing_with_existing_run(db, run_id=int(run.id))
