"""QQ 机器人推送配置服务。

为什么不直接改 `config/sources.example.yml`？
- 这个文件带了很多项目说明注释，用 PyYAML 回写会把注释冲掉。
- 真正部署时，敏感字段如 access_token 不应该进仓库。

所以这里采用“两层配置”：
1. `sources.example.yml` 提供默认配置和说明。
2. `config/push.local.json` 保存前端页面写入的本地/服务器配置，并已加入 `.gitignore`。

运行时会把两层配置合并，再由 `push_service` 支持环境变量覆盖。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from app.core.config import PROJECT_ROOT, settings
from app.core.secrets import decrypt_secret, encrypt_secret
from app.services.push_service import apply_env_overrides

PUSH_LOCAL_CONFIG_PATH = Path(PROJECT_ROOT / "config" / "push.local.json")

DEFAULT_PUSH_CONFIG: dict[str, Any] = {
    "channel": "qq_bot",
    "enabled": False,
    "onebot_api_base": "http://127.0.0.1:3000",
    "target_type": "private",
    "user_id": "",
    "group_id": "",
    "access_token": "",
    "retry_times": 3,
    "timeout_seconds": 10,
    "max_chars": 3500,
    "allow_partial_success": True,
}


class PushConfigPayload(BaseModel):
    """前端可编辑的 QQ 推送配置。"""

    channel: str = "qq_bot"
    enabled: bool = False
    onebot_api_base: str = "http://127.0.0.1:3000"
    target_type: Literal["private", "group"] = "private"
    user_id: str = ""
    group_id: str = ""
    # 空字符串表示不修改已有 token，避免前端拿不到明文 token 时误清空。
    access_token: str | None = None
    retry_times: int = Field(default=3, ge=1, le=10)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    max_chars: int = Field(default=3500, ge=500, le=10000)
    allow_partial_success: bool = True


def mask_secret(value: str | None) -> str:
    """返回脱敏 token，接口响应永不直接暴露完整 token。"""
    if not value:
        return ""
    if len(value) <= 8:
        return value[:2] + "***"
    return value[:4] + "***" + value[-4:]


def _load_base_push_config() -> dict[str, Any]:
    if not settings.sources_config_path.exists():
        return dict(DEFAULT_PUSH_CONFIG)
    data = yaml.safe_load(settings.sources_config_path.read_text(encoding="utf-8")) or {}
    return {**DEFAULT_PUSH_CONFIG, **(data.get("push") or {})}


def _load_local_push_config() -> dict[str, Any]:
    if not PUSH_LOCAL_CONFIG_PATH.exists():
        return {}
    try:
        root = json.loads(PUSH_LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))
        data = root.get("push") or {}
        stored_token = str(data.get("access_token") or "")
        if stored_token and not stored_token.startswith("enc:v1:"):
            root["push"] = {**data, "access_token": encrypt_secret(stored_token)}
            PUSH_LOCAL_CONFIG_PATH.write_text(json.dumps(root, ensure_ascii=False, indent=2), encoding="utf-8")
        return {**data, "access_token": decrypt_secret(stored_token)}
    except Exception:  # noqa: BLE001
        return {}


def load_push_config(*, include_env: bool = False, mask_token: bool = False) -> dict[str, Any]:
    """读取合并后的推送配置。"""
    cfg = {**_load_base_push_config(), **_load_local_push_config()}
    if include_env:
        cfg = apply_env_overrides(cfg)
    if mask_token:
        cfg = dict(cfg)
        cfg["access_token_masked"] = mask_secret(str(cfg.get("access_token") or ""))
        cfg["access_token"] = ""
        cfg["local_config_path"] = str(PUSH_LOCAL_CONFIG_PATH)
    return cfg


def save_push_config(payload: PushConfigPayload) -> dict[str, Any]:
    """保存前端提交的推送配置到 `config/push.local.json`。"""
    existing = load_push_config(include_env=False, mask_token=False)
    data = payload.model_dump(mode="json")

    # 前端 token 输入框为空时，表示沿用已有 token。
    if not data.get("access_token"):
        data["access_token"] = existing.get("access_token", "")

    data["channel"] = "qq_bot"
    data["onebot_api_base"] = str(data.get("onebot_api_base") or "").strip().rstrip("/")
    data["user_id"] = str(data.get("user_id") or "").strip()
    data["group_id"] = str(data.get("group_id") or "").strip()
    data["access_token"] = str(data.get("access_token") or "").strip()

    PUSH_LOCAL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    persisted = {**data, "access_token": encrypt_secret(data.get("access_token"))}
    PUSH_LOCAL_CONFIG_PATH.write_text(
        json.dumps({"push": persisted}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return load_push_config(include_env=True, mask_token=True)
