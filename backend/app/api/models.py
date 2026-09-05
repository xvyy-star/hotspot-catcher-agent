"""AI 模型配置 API。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AIModelProvider
from app.db.session import get_db
from app.services.llm_observability_service import get_llm_stats
from app.services.model_provider_service import (
    ModelProviderPayload,
    ModelProviderConflictError,
    ModelProviderNotFoundError,
    TestProviderPayload,
    delete_provider_permanently,
    fetch_model_ids,
    provider_to_dict,
    test_chat_completion,
    update_provider_test_result,
    upsert_provider,
    provider_api_key,
)
from app.services.system_log_service import write_system_log

router = APIRouter(prefix="/models", tags=["models"])


@router.get("/stats")
def model_call_stats(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    """模型调用统计。"""
    return {"data": get_llm_stats(db, limit=limit)}


@router.get("/providers")
def list_providers(db: Session = Depends(get_db)):
    rows = db.execute(
        select(AIModelProvider).order_by(AIModelProvider.priority.asc(), AIModelProvider.id.asc())
    ).scalars()
    return {"data": [provider_to_dict(row) for row in rows]}


@router.post("/providers")
def create_provider(payload: ModelProviderPayload, db: Session = Depends(get_db)):
    try:
        provider = upsert_provider(db, payload)
    except ModelProviderConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    write_system_log(
        db,
        level="INFO",
        module="models",
        message=f"创建模型通道：{provider.name}",
        extra={"provider_id": provider.id, "code": provider.code},
        commit=True,
    )
    return {"data": provider_to_dict(provider)}


@router.put("/providers/{provider_id}")
def update_provider(provider_id: int, payload: ModelProviderPayload, db: Session = Depends(get_db)):
    try:
        provider = upsert_provider(db, payload, provider_id=provider_id)
    except ModelProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ModelProviderConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    write_system_log(
        db,
        level="INFO",
        module="models",
        message=f"更新模型通道：{provider.name}",
        extra={"provider_id": provider.id, "code": provider.code, "enabled": provider.enabled},
        commit=True,
    )
    return {"data": provider_to_dict(provider)}


@router.delete("/providers/{provider_id}")
def delete_provider(provider_id: int, db: Session = Depends(get_db)):
    provider = db.get(AIModelProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    deleted = delete_provider_permanently(db, provider)
    write_system_log(
        db,
        level="INFO",
        module="models",
        message=f"删除模型通道：{deleted['name'] or deleted['code']}",
        extra={"provider": deleted},
        commit=True,
    )
    return {"ok": True, "data": deleted}


@router.post("/providers/{provider_id}/models")
def fetch_provider_models(provider_id: int, db: Session = Depends(get_db)):
    provider = db.get(AIModelProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    try:
        models = fetch_model_ids(provider.base_url, provider_api_key(provider), timeout_seconds=provider.timeout_seconds)
        return {"ok": True, "data": models}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"获取模型列表失败：{exc}") from exc


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: int, db: Session = Depends(get_db)):
    provider = db.get(AIModelProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    result = test_chat_completion(
        provider.base_url,
        provider.model,
        provider_api_key(provider),
        timeout_seconds=provider.timeout_seconds,
    )
    update_provider_test_result(db, provider, bool(result["ok"]), str(result["message"]))
    return result


@router.post("/probe/models")
def probe_models(payload: TestProviderPayload):
    try:
        models = fetch_model_ids(payload.base_url, payload.api_key, timeout_seconds=payload.timeout_seconds)
        return {"ok": True, "data": models}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"获取模型列表失败：{exc}") from exc


@router.post("/probe/test")
def probe_test(payload: TestProviderPayload, model: str = Query("")):
    chosen_model = model or payload.model
    if not chosen_model:
        raise HTTPException(status_code=400, detail="请先选择模型")
    return test_chat_completion(
        payload.base_url,
        chosen_model,
        payload.api_key,
        timeout_seconds=payload.timeout_seconds,
    )
