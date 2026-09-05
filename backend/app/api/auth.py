"""管理员登录与个人信息 API。

交付策略：
- 登录成功后签发独立的会话 token（P0-1），存入 Redis，支持主动吊销。
- 登录失败锁定迁移到 Redis（P0-2），多 worker/多实例共享。
- 密码校验优先 bcrypt（P0-7），移除明文密码支持。
- 登录失败、锁定、成功、退出全部写入 system_log。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import extract_admin_token, hash_password_bcrypt, resolve_client_ip, valid_admin_password
from app.db.session import get_db
from app.services.session_service import (
    create_session,
    get_login_state,
    is_login_locked,
    record_login_failure,
    reset_login_failures,
    revoke_session,
)
from app.services.system_log_service import write_system_log

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginPayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=500)
    remember: bool = False


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _credential_hint(token: str | None = None) -> str:
    value = token or settings.admin_token or ""
    if len(value) >= 10:
        return f"{value[:4]}***{value[-4:]}"
    return "***"


def _avatar_text(display_name: str, username: str) -> str:
    base = (display_name or username or "HA").strip()
    if not base:
        return "HA"
    if all(ord(ch) < 128 for ch in base):
        return base[:2].upper()
    return base[:2]


def _profile_dict(
    *,
    auth_mode: str = "password",
    ip: str | None = None,
    login_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    display_name = settings.admin_display_name or settings.admin_username
    state = login_state or {}
    return {
        "username": settings.admin_username,
        "display_name": display_name,
        "role": settings.admin_role,
        "avatar_text": _avatar_text(display_name, settings.admin_username),
        "permissions": [
            "briefing:generate",
            "events:read",
            "knowledge:manage",
            "system:observe",
            "config:manage",
        ],
        "auth_mode": auth_mode,
        "auth_modes": ["password"],
        "api_auth_enabled": settings.api_auth_enabled,
        "login_security": {
            "client_ip": ip,
            "failed_count": state.get("failed_count", 0),
            "locked_until": state.get("locked_until"),
            "is_locked": state.get("is_locked", False),
            "failure_limit": settings.login_failure_limit,
            "lock_seconds": settings.login_lock_seconds,
            "password_enabled": bool(
                settings.admin_password_bcrypt or settings.admin_password_sha256
            ),
            "password_hash_configured": bool(settings.admin_password_bcrypt),
        },
    }


def _record_failure(
    db: Session,
    *,
    username: str,
    ip: str,
    reason: str,
) -> tuple[int, bool, int]:
    """P0-2: 使用 Redis 记录登录失败。返回 (failed_count, is_locked, lock_seconds)。"""
    failed_count, is_locked, lock_seconds = record_login_failure(username, ip)
    if is_locked:
        level = "WARNING"
        message = "管理员登录失败次数过多，账号临时锁定"
    else:
        level = "WARNING"
        message = "管理员登录失败"
    write_system_log(
        db,
        level=level,
        module="auth",
        message=message,
        extra={
            "username": username,
            "ip": ip,
            "reason": reason,
            "failed_count": failed_count,
            "is_locked": is_locked,
        },
        commit=True,
    )
    return failed_count, is_locked, lock_seconds


def _record_success(
    db: Session,
    *,
    username: str,
    ip: str,
) -> None:
    reset_login_failures(username, ip)
    write_system_log(
        db,
        level="INFO",
        module="auth",
        message="管理员登录成功",
        extra={"username": username, "ip": ip},
        commit=True,
    )


@router.post("/login")
def login(payload: LoginPayload, request: Request, db: Session = Depends(get_db)) -> dict:
    """校验管理员账号和密码，签发会话 token。

    P0-1: 返回的 token 是独立的会话凭据（非静态 ADMIN_TOKEN），支持主动吊销。
    """
    username = payload.username.strip()
    ip = resolve_client_ip(request)

    # P0-2: 先检查 Redis 锁定状态
    locked, retry_after = is_login_locked(username or settings.admin_username, ip)
    if locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"登录失败次数过多，请 {retry_after} 秒后再试。",
            headers={"Retry-After": str(retry_after)},
        )

    username_ok = username == settings.admin_username
    credential_ok = valid_admin_password(payload.password)

    if settings.api_auth_enabled and (not username_ok or not credential_ok):
        failed_count, is_locked, lock_seconds = _record_failure(
            db,
            username=username or "-",
            ip=ip,
            reason="username_or_credential_invalid",
        )
        if is_locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"登录失败次数过多，请 {lock_seconds} 秒后再试。",
                headers={"Retry-After": str(lock_seconds)},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="管理员账号或密码不正确。",
        )

    _record_success(db, username=username, ip=ip)

    # P0-1: 签发独立的会话 token
    session_token, ttl = create_session(
        username=username,
        ip=ip,
        remember=payload.remember,
    )

    login_state = get_login_state(username, ip)
    return {
        "ok": True,
        "data": {
            "token": session_token,
            "profile": _profile_dict(auth_mode="password", ip=ip, login_state=login_state),
            "login_at": datetime.utcnow().isoformat(),
            "expires_in": ttl,
        },
    }


@router.get("/me")
def current_user(request: Request) -> dict:
    """返回当前管理员资料。中间件已完成 API 凭据校验。"""
    ip = resolve_client_ip(request)
    login_state = get_login_state(settings.admin_username, ip)
    return {
        "data": _profile_dict(
            auth_mode="password",
            ip=ip,
            login_state=login_state,
        )
    }


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)) -> dict:
    """P0-1: 吊销当前会话 token。"""
    ip = resolve_client_ip(request)
    token = extract_admin_token(request)

    revoked = False
    if token:
        revoked = revoke_session(token)

    write_system_log(
        db,
        level="INFO",
        module="auth",
        message="管理员退出登录" + ("（会话已吊销）" if revoked else "（无有效会话）"),
        extra={
            "username": settings.admin_username,
            "ip": ip,
            "credential_hint": _credential_hint(token),
            "revoked": revoked,
        },
        commit=True,
    )
    return {"ok": True, "message": "已退出登录。", "revoked": revoked}


class ChangePasswordPayload(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=500)
    new_password: str = Field(..., min_length=6, max_length=500)
    confirm_password: str = Field(..., min_length=6, max_length=500)


class UpdateProfilePayload(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=64)


@router.post("/change-password")
def change_password(payload: ChangePasswordPayload, request: Request, db: Session = Depends(get_db)) -> dict:
    """修改管理员密码。需验证旧密码。"""
    ip = resolve_client_ip(request)
    if not valid_admin_password(payload.old_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前密码不正确，请确认后重试。",
        )
    if payload.new_password != payload.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="两次输入的新密码不一致。",
        )
    if len(payload.new_password.strip()) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码长度不能少于 6 位。",
        )

    new_hash = hash_password_bcrypt(payload.new_password)
    settings.admin_password_bcrypt = new_hash

    write_system_log(
        db,
        level="INFO",
        module="auth",
        message="管理员成功修改登录密码",
        extra={"username": settings.admin_username, "ip": ip},
        commit=True,
    )
    return {"ok": True, "message": "密码修改成功，新密码已生效。"}


@router.put("/profile")
def update_profile(payload: UpdateProfilePayload, request: Request, db: Session = Depends(get_db)) -> dict:
    """更新管理员个人资料。"""
    ip = resolve_client_ip(request)
    cleaned_name = payload.display_name.strip()
    if not cleaned_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="显示昵称不能为空。")

    settings.admin_display_name = cleaned_name
    login_state = get_login_state(settings.admin_username, ip)

    write_system_log(
        db,
        level="INFO",
        module="auth",
        message="管理员更新个人资料",
        extra={"username": settings.admin_username, "display_name": cleaned_name, "ip": ip},
        commit=True,
    )
    return {
        "ok": True,
        "message": "个人资料已更新。",
        "data": _profile_dict(auth_mode="password", ip=ip, login_state=login_state),
    }


@router.post("/reset-failures")
def reset_failures(request: Request, db: Session = Depends(get_db)) -> dict:
    """重置当前客户端 IP 的登录失败记录和安全锁定状态。"""
    ip = resolve_client_ip(request)
    reset_login_failures(settings.admin_username, ip)
    write_system_log(
        db,
        level="INFO",
        module="auth",
        message="管理员手动重置安全失败计数",
        extra={"username": settings.admin_username, "ip": ip},
        commit=True,
    )
    return {"ok": True, "message": "已重置登录失败计数与安全防护状态。"}
