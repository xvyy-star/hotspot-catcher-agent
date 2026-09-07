"""Account persistence and password lifecycle, independent of Redis sessions."""

from __future__ import annotations

import hashlib
import hmac
import re

import bcrypt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AppUser

ADMIN_ROLES = frozenset({"owner", "admin"})
USERNAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.-]{2,31}\Z", re.ASCII)
USER_PERMISSIONS = ["events:read", "feedback:write", "profile:manage"]
ADMIN_PERMISSIONS = USER_PERMISSIONS + [
    "briefing:generate",
    "knowledge:manage",
    "system:observe",
    "config:manage",
    "users:manage",
]


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_username(username: str) -> str:
    normalized = normalize_username(username)
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise ValueError("用户名需为 3 至 32 位英文字母、数字、下划线、点或短横线，且以字母或数字开头。")
    return normalized


def validate_new_password(password: str, confirmation: str) -> None:
    if password != confirmation:
        raise ValueError("两次输入的密码不一致。")
    if len(password) < 8 or len(password.encode("utf-8")) > 72:
        raise ValueError("密码至少 8 个字符，UTF-8 编码长度至多 72 字节。")
    if not password.strip():
        raise ValueError("密码需包含非空白字符。")


def hash_user_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_user_password(user: AppUser, password: str) -> bool:
    raw = password.encode("utf-8")
    if user.password_hash.startswith("sha256$"):
        return hmac.compare_digest(hashlib.sha256(raw).hexdigest(), user.password_hash[7:])
    if len(raw) > 72:
        return False
    try:
        return bcrypt.checkpw(raw, user.password_hash.encode("utf-8"))
    except (TypeError, ValueError):
        return False


def bootstrap_admin(db: Session) -> AppUser | None:
    """Import deployment credentials once; later config changes never overwrite accounts."""
    existing = db.scalar(select(AppUser).where(AppUser.role.in_(ADMIN_ROLES)).order_by(AppUser.id).limit(1))
    if existing is not None:
        return existing
    username = normalize_username(settings.admin_username)
    collision = db.scalar(select(AppUser).where(AppUser.username == username))
    if collision is not None:
        raise RuntimeError("Configured administrator username is already occupied by a non-admin account")
    password_hash = settings.admin_password_bcrypt.strip()
    if not password_hash and settings.admin_password_sha256.strip():
        password_hash = "sha256$" + settings.admin_password_sha256.strip()
    if not password_hash:
        return None
    user = AppUser(
        username=username,
        display_name=settings.admin_display_name or username,
        password_hash=password_hash,
        role="owner",
        is_active=True,
        auth_version=1,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Multiple workers may bootstrap simultaneously; only the unique account wins.
        existing = db.scalar(select(AppUser).where(AppUser.username == username))
        if existing is None or existing.role not in ADMIN_ROLES:
            raise
        return existing
    db.refresh(user)
    return user


def user_to_dict(user: AppUser) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def user_principal(user: AppUser) -> dict:
    return {
        **user_to_dict(user),
        "auth_version": user.auth_version,
        "auth_mode": "password",
        "password_enabled": bool(user.password_hash),
        "password_hash_configured": user.password_hash.startswith("$2"),
    }
