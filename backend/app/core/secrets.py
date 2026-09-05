"""应用内部 Secret 加解密工具。"""
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger(__name__)
_PREFIX = "enc:v1:"
_DEV_FALLBACK_SEED = "fallback-dev-only-not-for-production"
# 只告警一次，避免刷屏；进程级即可。
_warned_missing_secret = False


def _fernet() -> Fernet:
    # 敏感字段（如第三方大模型 api_key）以密文入库。
    # 加密密钥优先取 APP_SECRET_KEY；未配置时回退到 ADMIN_TOKEN，最后才用开发兜底种子。
    # 兜底种子对所有部署都相同，等同于「没有加密」，因此在缺少独立密钥时必须显式告警，
    # 而不是像以前一样默认静默兜底。
    global _warned_missing_secret
    if not settings.app_secret_key and not _warned_missing_secret:
        if settings.admin_token:
            logger.warning(
                "APP_SECRET_KEY 未配置，敏感字段加密回退到 ADMIN_TOKEN；"
                "生产环境请设置独立的 APP_SECRET_KEY（≥32 字符），避免密钥与登录令牌复用。"
            )
        else:
            logger.warning(
                "APP_SECRET_KEY 与 ADMIN_TOKEN 均未配置，敏感字段加密正在使用固定的开发兜底密钥，"
                "此时数据库中的 api_key 等同于未加密。生产环境必须设置 APP_SECRET_KEY。"
            )
        _warned_missing_secret = True

    seed = (settings.app_secret_key or settings.admin_token or _DEV_FALLBACK_SEED).encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(seed).digest())
    return Fernet(key)


def encrypt_secret(value: str | None) -> str | None:
    if value is None:
        return None
    value = str(value)
    if not value or value.startswith(_PREFIX):
        return value
    token = _fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return f"{_PREFIX}{token}"


def decrypt_secret(value: str | None) -> str:
    if not value:
        return ""
    raw = str(value)
    if not raw.startswith(_PREFIX):
        # 兼容旧库里的明文 Key；保存时会自动改为密文。
        return raw
    try:
        return _fernet().decrypt(raw[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        logger.warning("Secret 解密失败：%s", exc)
        return ""


def mask_secret(value: str | None) -> str:
    plain = decrypt_secret(value)
    if not plain:
        return ""
    if len(plain) <= 10:
        return "***"
    return f"{plain[:6]}...{plain[-4:]}"
