"""知识库 / RAG API。"""
from __future__ import annotations

import json
import time
from datetime import date
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, get_db
from app.services.embedding_service import EmbeddingService
from app.services.knowledge_async_tasks import run_briefing_ingest_task, run_file_ingest_task, run_text_ingest_task, run_vector_reindex_task
from app.services.knowledge_file_parser import MAX_UPLOAD_BYTES, parse_knowledge_file, parse_upload_tags, validate_knowledge_file_input
from app.services.knowledge_service import KnowledgeService
from app.services.qdrant_service import QdrantService

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class KnowledgeDocumentPayload(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=10)
    source: str | None = None
    tags: list[str] = Field(default_factory=list)
    chunk_size: int = Field(default=700, ge=200, le=1500)
    overlap: int = Field(default=100, ge=0, le=500)


class KnowledgeSearchPayload(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[int] = Field(default_factory=list)


class KnowledgeAskPayload(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    document_ids: list[int] = Field(default_factory=list)


class KnowledgeBriefingIngestPayload(BaseModel):
    briefing_date: date | None = None
    chunk_size: int = Field(default=800, ge=200, le=1500)
    overlap: int = Field(default=120, ge=0, le=500)


class KnowledgeEmbeddingTestPayload(BaseModel):
    text: str = Field(default="AI Agent 热点捕手 RAG 向量模型连通性测试", min_length=1, max_length=2000)


class KnowledgeVectorReindexPayload(BaseModel):
    document_id: int | None = Field(default=None, ge=1)
    batch_size: int = Field(default=16, ge=1, le=64)
    recreate_collection: bool = False


@router.get("/health")
def knowledge_health() -> dict[str, Any]:
    """检查 Qdrant 知识库集合状态。"""
    return {"data": QdrantService().health()}


@router.post("/embedding/test")
def test_knowledge_embedding(payload: KnowledgeEmbeddingTestPayload | None = None) -> dict[str, Any]:
    """测试当前 Embedding 配置。

    返回模型、维度、耗时和 provider，不返回 API Key。
    """
    payload = payload or KnowledgeEmbeddingTestPayload()
    service = EmbeddingService()
    started = time.perf_counter()
    try:
        vector = service.embed_query(payload.text)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "ok": True,
            "data": {
                "ok": True,
                "provider": service.provider,
                "model": service.model,
                "dimension": len(vector),
                "configured_dimension": service.dimension,
                "latency_ms": latency_ms,
                "fallback": service.provider.startswith("local-hashing"),
                "error_message": service.last_error,
            },
        }
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "ok": False,
            "data": {
                "ok": False,
                "provider": service.provider,
                "model": service.model,
                "dimension": 0,
                "configured_dimension": service.dimension,
                "latency_ms": latency_ms,
                "fallback": False,
                "error_message": str(exc),
            },
        }


@router.get("/documents")
def list_knowledge_documents(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    return {"data": KnowledgeService().list_documents(db, limit=limit)}


@router.get("/ingest-runs")
def list_knowledge_ingest_runs(
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(default=None),
    document_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    """知识库导入任务列表。

    用于前端展示导入进度、失败原因、chunk 数和耗时。
    """
    return {
        "data": KnowledgeService().list_ingest_runs(
            db,
            limit=limit,
            status=status,
            document_id=document_id,
        )
    }


@router.get("/ingest-runs/{run_id}")
def get_knowledge_ingest_run(run_id: int, db: Session = Depends(get_db)):
    data = KnowledgeService().get_ingest_run(db, run_id)
    if not data:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    return {"data": data}


@router.post("/reindex/async")
def reindex_knowledge_vectors_async(
    payload: KnowledgeVectorReindexPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """异步重建知识库向量。

    用于更换 embedding 模型或 Qdrant collection 后，把 MySQL 里的 chunk 重新写入向量库。
    """
    if payload.document_id is not None and payload.recreate_collection:
        raise HTTPException(status_code=400, detail="重建整个 collection 时不能只选择单个文档")
    try:
        run = KnowledgeService().create_queued_run(db)
        background_tasks.add_task(
            run_vector_reindex_task,
            run_id=int(run["id"]),
            document_id=payload.document_id,
            batch_size=payload.batch_size,
            recreate_collection=payload.recreate_collection,
        )
        return {"ok": True, "data": run}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"创建向量重建任务失败：{exc}") from exc


@router.post("/documents")
def create_knowledge_document(payload: KnowledgeDocumentPayload, db: Session = Depends(get_db)):
    try:
        data = KnowledgeService().create_document(
            db,
            title=payload.title,
            content=payload.content,
            source=payload.source,
            tags=payload.tags,
            chunk_size=payload.chunk_size,
            overlap=payload.overlap,
        )
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"知识库导入失败：{exc}") from exc


@router.post("/documents/async")
def create_knowledge_document_async(
    payload: KnowledgeDocumentPayload,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """异步导入纯文本文档。

    返回 run_id 后，前端轮询 `/api/knowledge/ingest-runs/{run_id}` 查看状态。
    """
    try:
        run = KnowledgeService().create_queued_run(db)
        background_tasks.add_task(
            run_text_ingest_task,
            run_id=int(run["id"]),
            title=payload.title,
            content=payload.content,
            source=payload.source,
            tags=payload.tags,
            chunk_size=payload.chunk_size,
            overlap=payload.overlap,
        )
        return {"ok": True, "data": run}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"创建异步导入任务失败：{exc}") from exc


@router.post("/documents/upload")
async def upload_knowledge_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    source: str | None = Form(default="upload"),
    tags: str = Form(default=""),
    chunk_size: int = Form(default=700, ge=200, le=1500),
    overlap: int = Form(default=100, ge=0, le=500),
    db: Session = Depends(get_db),
):
    """上传文件并导入知识库。

    支持 txt / md / pdf / docx。扫描版 PDF 暂不做 OCR，后续可扩展。
    """
    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        parsed = parse_knowledge_file(file.filename or "untitled", content, file.content_type)
        doc_title = (title or parsed.title).strip()[:255]
        parsed_tags = parse_upload_tags(tags)
        if parsed.file_ext not in parsed_tags:
            parsed_tags.append(parsed.file_ext)

        data = KnowledgeService().create_document(
            db,
            title=doc_title,
            content=parsed.text,
            source=source or f"upload:{parsed.file_name}",
            tags=parsed_tags,
            chunk_size=chunk_size,
            overlap=overlap,
        )
        data["upload"] = parsed.metadata
        return {"ok": True, "data": data}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"文件导入知识库失败：{exc}") from exc


@router.post("/documents/upload/async")
async def upload_knowledge_document_async(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    source: str | None = Form(default="upload"),
    tags: str = Form(default=""),
    chunk_size: int = Form(default=700, ge=200, le=1500),
    overlap: int = Form(default=100, ge=0, le=500),
    db: Session = Depends(get_db),
):
    """异步上传文件并导入知识库。

    当前用 FastAPI BackgroundTasks；生产可替换为 Celery/RQ。
    """
    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        validate_knowledge_file_input(file.filename or "untitled", content)
        run = KnowledgeService().create_queued_run(db)
        background_tasks.add_task(
            run_file_ingest_task,
            run_id=int(run["id"]),
            file_name=file.filename or "untitled",
            content=content,
            content_type=file.content_type,
            title=title,
            source=source,
            tags_text=tags,
            chunk_size=chunk_size,
            overlap=overlap,
        )
        return {"ok": True, "data": run}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"创建异步文件导入任务失败：{exc}") from exc


@router.get("/documents/{document_id}")
def get_knowledge_document(document_id: int, db: Session = Depends(get_db)):
    data = KnowledgeService().get_document(db, document_id)
    if not data:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"data": data}


@router.delete("/documents/{document_id}")
def delete_knowledge_document(document_id: int, db: Session = Depends(get_db)):
    ok = KnowledgeService().delete_document(db, document_id)
    if not ok:
        raise HTTPException(status_code=404, detail="文档不存在")
    return {"ok": True}


@router.post("/search")
def search_knowledge(payload: KnowledgeSearchPayload, db: Session = Depends(get_db)):
    try:
        rows = KnowledgeService().search(db, payload.query, payload.top_k, payload.document_ids)
        return {"data": [KnowledgeService.search_result_to_dict(row) for row in rows]}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ask")
def ask_knowledge(payload: KnowledgeAskPayload, db: Session = Depends(get_db)):
    try:
        return {"data": KnowledgeService().ask(db, payload.question, payload.top_k, payload.document_ids)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ask/stream")
def ask_knowledge_stream(payload: KnowledgeAskPayload):
    """流式知识问答。

    返回 application/x-ndjson，前端用 fetch + ReadableStream 逐行消费。
    """

    def iter_events():
        try:
            with SessionLocal() as db:
                service = KnowledgeService()
                for event in service.ask_stream(db, payload.question, payload.top_k, payload.document_ids):
                    yield (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
        except Exception as exc:  # noqa: BLE001
            yield (json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False) + "\n").encode("utf-8")

    return StreamingResponse(iter_events(), media_type="application/x-ndjson; charset=utf-8")


@router.post("/ingest/latest-briefing")
def ingest_latest_briefing(db: Session = Depends(get_db)):
    """把最新一份早报写入知识库，形成历史热点记忆。"""
    try:
        return {"ok": True, "data": KnowledgeService().ingest_today_briefing(db)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"导入历史早报失败：{exc}") from exc


@router.post("/ingest/latest-briefing/async")
def ingest_latest_briefing_async(
    background_tasks: BackgroundTasks,
    payload: KnowledgeBriefingIngestPayload | None = None,
    db: Session = Depends(get_db),
):
    """异步把指定日期或最新早报写入知识库。

    返回 run_id 后，前端轮询 `/api/knowledge/ingest-runs/{run_id}` 查看状态。
    """
    try:
        payload = payload or KnowledgeBriefingIngestPayload()
        run = KnowledgeService().create_queued_run(db)
        background_tasks.add_task(
            run_briefing_ingest_task,
            run_id=int(run["id"]),
            briefing_date=payload.briefing_date.isoformat() if payload.briefing_date else None,
            chunk_size=payload.chunk_size,
            overlap=payload.overlap,
        )
        return {"ok": True, "data": run}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"创建历史早报异步入库任务失败：{exc}") from exc
