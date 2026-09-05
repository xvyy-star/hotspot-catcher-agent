"""AI 模型 Provider 管理服务。

企业级项目里，模型配置不能只写死在环境变量里：
- 本地开发可能有一个代理模型。
- 线上可能有一个付费稳定模型。
- 不同模型要支持优先级、启停、连通性测试、模型列表拉取。

本模块把这些能力集中封装，供 API 和 LangChain 分析链共用。
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

import requests
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.secrets import decrypt_secret, encrypt_secret, mask_secret
from app.db.models import AIModelProvider, DeletedModelProvider


class ModelProviderPayload(BaseModel):
    code: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1)
    api_key: str | None = None
    model: str = Field(min_length=1, max_length=160)
    priority: int = 100
    enabled: bool = True
    requires_api_key: bool = True
    timeout_seconds: int = Field(default=60, ge=5, le=180)
    max_tokens: int = Field(default=800, ge=50, le=8000)
    temperature: float = Field(default=0.2, ge=0, le=2)
    input_cost_per_million: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        max_digits=18,
        decimal_places=8,
        description="USD per 1M input tokens",
    )
    output_cost_per_million: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        max_digits=18,
        decimal_places=8,
        description="USD per 1M output tokens",
    )
    note: str | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", normalized):
            raise ValueError("Code 只能包含小写字母、数字、点、下划线和连字符")
        return normalized

    @field_validator("name", "model", mode="before")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("名称和模型不能为空")
        return normalized

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = str(value or "").strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Base URL 必须是有效的 http(s) 地址")
        if parsed.username or parsed.password:
            raise ValueError("Base URL 中不能包含账号或密码")
        return normalized


class TestProviderPayload(BaseModel):
    base_url: str
    api_key: str | None = None
    model: str | None = None
    timeout_seconds: int = Field(default=30, ge=5, le=180)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return ModelProviderPayload.validate_base_url(value)


DEFAULT_PROVIDER_CODES = {"environment"}


class ModelProviderNotFoundError(LookupError):
    pass


class ModelProviderConflictError(ValueError):
    pass


def _normalized_url(value: str | None) -> str:
    return str(value or "").strip().rstrip("/")


def provider_uses_env_api_key(provider: AIModelProvider | None) -> bool:
    """是否允许该 Provider 复用 .env 里的 AI_API_KEY。

    只对默认 Agnes 通道或 base_url 与 AI_BASE_URL 完全一致的通道生效，避免把一个
    平台的 Key 错发到其他供应商。
    """
    if provider is None:
        return bool(settings.ai_api_key)
    if not settings.ai_api_key or settings.ai_api_key.startswith("dummy"):
        return False
    return provider.code == "environment" or bool(settings.ai_base_url and _normalized_url(provider.base_url) == _normalized_url(settings.ai_base_url))


def provider_api_key(provider: AIModelProvider | None) -> str:
    """返回 Provider 的明文 API Key，兼容环境变量与数据库加密字段。"""
    if provider is None:
        return decrypt_secret(settings.ai_api_key)
    own_key = decrypt_secret(provider.api_key)
    if own_key:
        return own_key
    if provider.requires_api_key and provider_uses_env_api_key(provider):
        return decrypt_secret(settings.ai_api_key)
    return ""


def provider_to_dict(provider: AIModelProvider, include_secret: bool = False) -> dict[str, Any]:
    data = {c.name: getattr(provider, c.name) for c in provider.__table__.columns}
    # Public API uses JSON numbers; database calculations retain Decimal precision.
    data["input_cost_per_million"] = float(provider.input_cost_per_million or 0)
    data["output_cost_per_million"] = float(provider.output_cost_per_million or 0)
    data["api_key_masked"] = mask_secret(provider.api_key)
    data["uses_env_api_key"] = bool(not decrypt_secret(provider.api_key) and provider_uses_env_api_key(provider))
    data["api_key_configured"] = bool(provider_api_key(provider)) or not provider.requires_api_key
    if not include_secret:
        data.pop("api_key", None)
    return data


def _deleted_provider_codes(db: Session) -> set[str]:
    return {str(code) for code in db.execute(select(DeletedModelProvider.code)).scalars() if str(code or "").strip()}


def _clear_deleted_marker(db: Session, code: str) -> None:
    normalized = str(code or "").strip()
    if not normalized:
        return
    db.execute(delete(DeletedModelProvider).where(DeletedModelProvider.code == normalized))


def delete_provider_permanently(db: Session, provider: AIModelProvider, *, deleted_by: str = "admin") -> dict[str, Any]:
    """真正删除模型通道，并记录删除标记，防止默认通道下次启动被自动补回。"""
    info = {
        "id": provider.id,
        "code": provider.code,
        "name": provider.name,
        "enabled": provider.enabled,
        "model": provider.model,
    }
    if provider.code in DEFAULT_PROVIDER_CODES:
        marker = db.execute(
            select(DeletedModelProvider).where(DeletedModelProvider.code == provider.code)
        ).scalar_one_or_none()
        if marker:
            marker.name = provider.name
            marker.deleted_by = deleted_by
            marker.created_at = datetime.utcnow()
        else:
            db.add(DeletedModelProvider(code=provider.code, name=provider.name, deleted_by=deleted_by))
    db.delete(provider)
    db.commit()
    return info


def _looks_corrupted_text(value: str | None) -> bool:
    text = str(value or "")
    if not text:
        return False
    markers = ("Ã", "Â", "â€", "ä", "å", "æ", "ç", "è", "é", "ï¼", "ã", "�")
    return sum(text.count(marker) for marker in markers) >= 2


def _headers(api_key: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    # MiMo 本地代理说明里 API Key 可任意填写或不填；远程兼容服务一般必须填。
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def fetch_model_ids(base_url: str, api_key: str | None = None, timeout_seconds: int = 20) -> list[str]:
    """从 OpenAI-compatible /models 拉取模型列表。"""
    resp = requests.get(
        f"{base_url.rstrip('/')}/models",
        headers=_headers(api_key),
        timeout=timeout_seconds,
    )
    resp.raise_for_status()
    data = resp.json()
    models = data.get("data", [])
    ids: list[str] = []
    for item in models:
        if isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]))
        elif isinstance(item, str):
            ids.append(item)
    return ids


def test_chat_completion(
    base_url: str,
    model: str,
    api_key: str | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """测试 Chat Completions 是否能真实返回内容。"""
    started = time.perf_counter()
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=_headers(api_key),
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "只输出严格 JSON，不要 Markdown。"},
                    {"role": "user", "content": '{"ping":"请返回 {\"ok\":true}"}'},
                ],
                "temperature": 0,
                "max_tokens": 80,
                "response_format": {"type": "json_object"},
            },
            timeout=timeout_seconds,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
    except requests.RequestException as exc:
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "message": f"模型服务连接失败：{exc}",
        }
    if resp.status_code >= 400:
        return {"ok": False, "status_code": resp.status_code, "latency_ms": latency_ms, "message": resp.text[:500]}
    try:
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        return {
            "ok": False,
            "status_code": resp.status_code,
            "latency_ms": latency_ms,
            "message": f"模型服务返回结构不正确：{exc}",
        }
    if not str(content).strip():
        return {
            "ok": False,
            "status_code": resp.status_code,
            "latency_ms": latency_ms,
            "message": "模型服务返回成功状态，但回答内容为空",
        }
    return {
        "ok": True,
        "status_code": resp.status_code,
        "latency_ms": latency_ms,
        "message": str(content)[:500],
    }


def ensure_default_providers(db: Session) -> None:
    """Only seed an explicitly configured provider into an empty database."""
    existing_codes = set(db.execute(select(AIModelProvider.code)).scalars())
    deleted_codes = _deleted_provider_codes(db)

    providers = [
        AIModelProvider(
            code="environment",
            name="Configured model service",
            base_url=os.getenv("AI_BASE_URL", settings.ai_base_url),
            api_key=encrypt_secret(os.getenv("AI_API_KEY", settings.ai_api_key)),
            model=os.getenv("AI_MODEL", settings.ai_model),
            priority=10,
            enabled=True,
            requires_api_key=True,
            timeout_seconds=60,
            max_tokens=800,
            temperature=0.2,
            note="默认远程 OpenAI-compatible 文本分析模型。",
        ),
    ] if not existing_codes and all((settings.ai_base_url, settings.ai_model, settings.ai_api_key)) else []
    missing = [provider for provider in providers if provider.code not in existing_codes and provider.code not in deleted_codes]
    if missing:
        db.add_all(missing)

    default_providers = {provider.code: provider for provider in providers}

    # 启动时顺手迁移旧明文 api_key，并修复早期错误编码导致的默认 Provider 文案。
    migrated = False
    for provider in db.execute(select(AIModelProvider)).scalars():
        default_provider = default_providers.get(provider.code)
        if default_provider:
            for key in ("name", "note"):
                current = getattr(provider, key, None)
                if _looks_corrupted_text(current):
                    setattr(provider, key, getattr(default_provider, key))
                    migrated = True
        if provider.api_key and not str(provider.api_key).startswith("enc:v1:"):
            provider.api_key = encrypt_secret(provider.api_key)
            migrated = True
    if missing or migrated:
        db.commit()


def get_enabled_providers(db: Session) -> list[AIModelProvider]:
    return list(
        db.execute(
            select(AIModelProvider)
            .where(AIModelProvider.enabled.is_(True))
            .order_by(AIModelProvider.priority.asc(), AIModelProvider.id.asc())
        ).scalars()
    )


def upsert_provider(db: Session, payload: ModelProviderPayload, provider_id: int | None = None) -> AIModelProvider:
    if provider_id is not None:
        provider = db.get(AIModelProvider, provider_id)
        if not provider:
            raise ModelProviderNotFoundError("模型配置不存在")
        if provider.code != payload.code:
            raise ModelProviderConflictError("模型通道 Code 创建后不可修改；请新建通道")
    else:
        provider = db.execute(select(AIModelProvider).where(AIModelProvider.code == payload.code)).scalar_one_or_none()
        if provider:
            raise ModelProviderConflictError(f"模型通道 Code 已存在：{payload.code}")
        provider = AIModelProvider(code=payload.code)
        db.add(provider)
    _clear_deleted_marker(db, payload.code)

    for key, value in payload.model_dump().items():
        if (
            provider_id is not None
            and key in {"input_cost_per_million", "output_cost_per_million"}
            and key not in payload.model_fields_set
        ):
            continue
        # 前端编辑已有 Provider 时不会回传明文密钥。
        # 如果 api_key 为空，保留数据库里的旧密钥，避免用户改个优先级就把 Key 清掉。
        if key == "api_key" and value in {None, ""} and getattr(provider, "api_key", None):
            continue
        if key == "api_key" and value:
            value = encrypt_secret(value)
        setattr(provider, key, value)
    db.commit()
    db.refresh(provider)
    return provider


def update_provider_test_result(db: Session, provider: AIModelProvider, ok: bool, message: str) -> None:
    provider.last_test_status = "SUCCESS" if ok else "FAILED"
    provider.last_test_message = message[:1000]
    provider.last_test_at = datetime.utcnow()
    db.commit()


