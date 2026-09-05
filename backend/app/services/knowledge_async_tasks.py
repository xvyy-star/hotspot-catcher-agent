"""知识库异步导入任务。

当前使用 FastAPI BackgroundTasks，适合本地演示和小规模部署。
企业生产可以平滑替换为 Celery / Dramatiq / RQ：
- API 层只负责创建 QUEUED run。
- Worker 根据 run_id 执行解析、切分、embedding、向量入库。
- 前端轮询 /api/knowledge/ingest-runs/{run_id} 展示进度。
"""
from __future__ import annotations

import logging
import threading
from datetime import date

from app.db.session import SessionLocal
from app.services.knowledge_file_parser import parse_knowledge_file, parse_upload_tags
from app.services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)


def run_text_ingest_task(
    *,
    run_id: int,
    title: str,
    content: str,
    source: str | None,
    tags: list[str] | None,
    chunk_size: int,
    overlap: int,
) -> None:
    """后台执行纯文本导入。"""
    service = KnowledgeService()
    with SessionLocal() as db:
        try:
            service.ingest_text_with_existing_run(
                db,
                run_id=run_id,
                title=title,
                content=content,
                source=source,
                tags=tags or [],
                chunk_size=chunk_size,
                overlap=overlap,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("异步文本导入失败 run_id=%s", run_id)
            service.update_ingest_run_status(db, run_id, "FAILED", error_message=str(exc), finished=True)


def run_file_ingest_task(
    *,
    run_id: int,
    file_name: str,
    content: bytes,
    content_type: str | None,
    title: str | None,
    source: str | None,
    tags_text: str,
    chunk_size: int,
    overlap: int,
) -> None:
    """后台执行文件解析与导入。"""
    service = KnowledgeService()
    with SessionLocal() as db:
        try:
            service.update_ingest_run_status(db, run_id, "PARSING")
            parsed = parse_knowledge_file(file_name, content, content_type)
            parsed_tags = parse_upload_tags(tags_text)
            if parsed.file_ext not in parsed_tags:
                parsed_tags.append(parsed.file_ext)
            doc_title = (title or parsed.title).strip()[:255]
            doc_source = source or f"upload:{parsed.file_name}"
            service.ingest_text_with_existing_run(
                db,
                run_id=run_id,
                title=doc_title,
                content=parsed.text,
                source=doc_source,
                tags=parsed_tags,
                chunk_size=chunk_size,
                overlap=overlap,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("异步文件导入失败 run_id=%s file=%s", run_id, file_name)
            service.update_ingest_run_status(db, run_id, "FAILED", error_message=str(exc), finished=True)


def run_briefing_ingest_task(
    *,
    run_id: int,
    briefing_date: str | None,
    chunk_size: int,
    overlap: int,
) -> None:
    """后台把每日早报导入知识库。

    briefing_date 使用 ISO 字符串，是为了方便 API / APScheduler / 线程任务之间传参。
    真正的数据库会话在后台线程里重新创建，避免跨线程复用 FastAPI 请求会话。
    """
    service = KnowledgeService()
    with SessionLocal() as db:
        try:
            day = date.fromisoformat(briefing_date) if briefing_date else None
            service.ingest_briefing_with_existing_run(
                db,
                run_id=run_id,
                briefing_date=day,
                chunk_size=chunk_size,
                overlap=overlap,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("异步早报入库失败 run_id=%s briefing_date=%s", run_id, briefing_date)
            service.update_ingest_run_status(db, run_id, "FAILED", error_message=str(exc), finished=True)


def enqueue_briefing_ingest_thread(
    *,
    briefing_date: date | None,
    chunk_size: int = 800,
    overlap: int = 120,
) -> dict:
    """给 APScheduler 等非 HTTP 场景使用的轻量异步入队。

    FastAPI BackgroundTasks 只能在请求生命周期里使用；定时任务里没有 HTTP Response，
    所以这里用守护线程启动后台导入。后续升级 Celery/RQ 时，只需要替换这个函数。
    """
    service = KnowledgeService()
    with SessionLocal() as db:
        run = service.create_queued_run(db)

    thread = threading.Thread(
        target=run_briefing_ingest_task,
        kwargs={
            "run_id": int(run["id"]),
            "briefing_date": briefing_date.isoformat() if briefing_date else None,
            "chunk_size": int(chunk_size),
            "overlap": int(overlap),
        },
        name=f"knowledge-briefing-ingest-{run['id']}",
        daemon=True,
    )
    try:
        thread.start()
    except Exception as exc:
        with SessionLocal() as db:
            service.update_ingest_run_status(
                db,
                int(run["id"]),
                "FAILED",
                error_message=f"后台线程启动失败：{exc}",
                finished=True,
            )
        raise
    return run


def run_vector_reindex_task(
    *,
    run_id: int,
    document_id: int | None,
    batch_size: int,
    recreate_collection: bool,
) -> None:
    """后台重建知识库向量。"""
    service = KnowledgeService()
    with SessionLocal() as db:
        try:
            service.reindex_vectors_with_existing_run(
                db,
                run_id=run_id,
                document_id=document_id,
                batch_size=batch_size,
                recreate_collection=recreate_collection,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("异步向量重建失败 run_id=%s document_id=%s", run_id, document_id)
            service.update_ingest_run_status(db, run_id, "FAILED", error_message=str(exc), finished=True)
