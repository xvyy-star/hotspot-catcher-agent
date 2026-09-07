"""Password authentication, registration, profiles and user administration."""

from __future__ import annotations
from datetime import datetime
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import extract_admin_token, get_current_principal, is_admin, resolve_client_ip
from app.db.models import AppUser
from app.db.session import get_db
from app.services.session_service import (
    create_session,
    get_login_state,
    revoke_session,
    is_login_locked,
    record_login_failure,
    reset_login_failures,
)
from app.services.user_service import (
    ADMIN_PERMISSIONS,
    USER_PERMISSIONS,
    bootstrap_admin,
    hash_user_password,
    normalize_username,
    user_principal,
    user_to_dict,
    validate_new_password,
    validate_username,
    verify_user_password,
)
from app.services.system_log_service import write_system_log

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginPayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=500)
    remember: bool = False


class RegisterPayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=500)
    confirm_password: str = Field(..., min_length=1, max_length=500)
    display_name: str | None = Field(default=None, max_length=64)


class ChangePasswordPayload(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=500)
    new_password: str = Field(..., min_length=1, max_length=500)
    confirm_password: str = Field(..., min_length=1, max_length=500)


class UpdateProfilePayload(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=64)


class ToggleUserPayload(BaseModel):
    is_active: bool


class ResetPasswordPayload(BaseModel):
    new_password: str = Field(..., min_length=1, max_length=500)
    confirm_password: str = Field(..., min_length=1, max_length=500)


def _permissions(role: str) -> list[str]:
    return list(ADMIN_PERMISSIONS if role in {"owner", "admin"} else USER_PERMISSIONS)


def _profile(user: AppUser, ip: str | None = None) -> dict[str, Any]:
    result = user_principal(user)
    result.pop("auth_version", None)
    result.update(
        permissions=_permissions(user.role),
        is_admin=is_admin({"role": user.role}),
        avatar_text=(user.display_name or user.username)[:2].upper(),
        auth_modes=["password"],
        api_auth_enabled=settings.api_auth_enabled,
    )
    result["login_security"] = {
        "client_ip": ip,
        "password_enabled": True,
        "password_hash_configured": user.password_hash.startswith("$2"),
        **get_login_state(user.username, ip or "unknown"),
        "failure_limit": settings.login_failure_limit,
        "lock_seconds": settings.login_lock_seconds,
    }
    return result


def _find_user(db: Session, username: str) -> AppUser | None:
    return db.scalar(select(AppUser).where(AppUser.username == normalize_username(username)))


def _audit(db: Session, request: Request, message: str, username: str) -> None:
    write_system_log(
        db,
        level="INFO",
        module="auth",
        message=message,
        extra={"username": username, "ip": resolve_client_ip(request)},
    )


def _locked_user(db: Session, user_id: int | None) -> AppUser:
    if user_id is None:
        raise HTTPException(status_code=403, detail="请使用账号密码登录后修改个人资料。")
    user = db.scalar(select(AppUser).where(AppUser.id == user_id).with_for_update())
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在。")
    return user


def _self_user(db: Session, request: Request) -> AppUser:
    principal = get_current_principal(request)
    user = _locked_user(db, principal.get("id"))
    if not user.is_active or user.auth_version != principal.get("auth_version"):
        raise HTTPException(status_code=401, detail="登录状态已失效，请重新登录。")
    return user


@router.get("/options")
def auth_options() -> dict:
    return {
        "data": {"registration_enabled": bool(settings.registration_enabled and settings.api_auth_enabled)}
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterPayload, request: Request, db: Session = Depends(get_db)) -> dict:
    if not settings.registration_enabled or not settings.api_auth_enabled:
        raise HTTPException(status_code=403, detail="注册功能未启用。")
    try:
        username = validate_username(payload.username)
        validate_new_password(payload.password, payload.confirm_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if username == normalize_username(settings.admin_username):
        raise HTTPException(status_code=409, detail="该用户名不可注册。")
    display_name = (payload.display_name or username).strip() or username
    if _find_user(db, username) is not None:
        raise HTTPException(status_code=409, detail="用户名已存在。")
    user = AppUser(
        username=username,
        display_name=display_name,
        password_hash=hash_user_password(payload.password),
        role="user",
        is_active=True,
    )
    db.add(user)
    try:
        _audit(db, request, "用户注册", username)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="用户名已存在。") from exc
    return {"ok": True, "message": "注册成功，请登录。"}


@router.post("/login")
def login(payload: LoginPayload, request: Request, db: Session = Depends(get_db)) -> dict:
    username, ip = normalize_username(payload.username), resolve_client_ip(request)
    locked, retry_after = is_login_locked(username, ip)
    if locked:
        raise HTTPException(
            status_code=429,
            detail=f"登录失败次数过多，请 {retry_after} 秒后再试。",
            headers={"Retry-After": str(retry_after)},
        )
    user = _find_user(db, username)
    if user is None and username == normalize_username(settings.admin_username):
        boot = bootstrap_admin(db)
        user = boot if boot and boot.username == username else None
    if user is None or not user.is_active or not verify_user_password(user, payload.password):
        _count, locked_now, seconds = record_login_failure(username or "-", ip)
        _audit(db, request, "登录失败，账号临时锁定" if locked_now else "登录失败", username)
        db.commit()
        if locked_now:
            raise HTTPException(
                status_code=429,
                detail=f"登录失败次数过多，请 {seconds} 秒后再试。",
                headers={"Retry-After": str(seconds)},
            )
        raise HTTPException(status_code=401, detail="账号或密码不正确。")
    reset_login_failures(username, ip)
    token, ttl = create_session(
        username=user.username,
        user_id=user.id,
        auth_version=user.auth_version,
        ip=ip,
        remember=payload.remember,
    )
    profile = _profile(user, ip)
    _audit(db, request, "登录成功", username)
    db.commit()
    return {
        "ok": True,
        "data": {
            "token": token,
            "profile": profile,
            "login_at": datetime.utcnow().isoformat(),
            "expires_in": ttl,
        },
    }


@router.get("/me")
def current_user(request: Request, db: Session = Depends(get_db)) -> dict:
    principal = get_current_principal(request)
    user = db.get(AppUser, principal.get("id")) if principal.get("id") else None
    return {
        "data": (
            _profile(user, resolve_client_ip(request))
            if user
            else {**principal, "permissions": _permissions(principal.get("role", "owner"))}
        )
    }


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)) -> dict:
    revoked = revoke_session(extract_admin_token(request))
    _audit(db, request, "退出登录", get_current_principal(request)["username"])
    db.commit()
    return {"ok": True, "message": "已退出登录。", "revoked": revoked}


@router.post("/change-password")
def change_password(payload: ChangePasswordPayload, request: Request, db: Session = Depends(get_db)) -> dict:
    user = _self_user(db, request)
    if user is None or not verify_user_password(user, payload.old_password):
        raise HTTPException(status_code=400, detail="当前密码不正确，请确认后重试。")
    try:
        validate_new_password(payload.new_password, payload.confirm_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    user.password_hash, user.auth_version = hash_user_password(payload.new_password), user.auth_version + 1
    _audit(db, request, "修改登录密码", user.username)
    db.commit()
    return {"ok": True, "message": "密码修改成功，请重新登录。"}


@router.put("/profile")
def update_profile(payload: UpdateProfilePayload, request: Request, db: Session = Depends(get_db)) -> dict:
    user = _self_user(db, request)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在。")
    name = payload.display_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="显示昵称不能为空。")
    user.display_name = name
    _audit(db, request, "更新个人资料", user.username)
    db.commit()
    return {"ok": True, "message": "个人资料已更新。", "data": _profile(user, resolve_client_ip(request))}


@router.post("/reset-failures")
def reset_failures(request: Request) -> dict:
    principal = get_current_principal(request)
    reset_login_failures(principal.get("username", ""), resolve_client_ip(request))
    return {"ok": True, "message": "已重置登录失败计数与安全防护状态。"}


def _require_admin(request: Request) -> dict:
    principal = get_current_principal(request)
    if not is_admin(principal):
        raise HTTPException(status_code=403, detail="此操作仅限管理员。")
    return principal


@router.get("/users")
def list_users(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str = Query("", max_length=64),
    db: Session = Depends(get_db),
) -> dict:
    _require_admin(request)
    term = keyword.strip().lower()
    query, count_query = select(AppUser), select(func.count()).select_from(AppUser)
    if term:
        clause = AppUser.username.contains(term, autoescape=True) | AppUser.display_name.contains(
            term, autoescape=True
        )
        query, count_query = query.where(clause), count_query.where(clause)
    total = int(db.scalar(count_query) or 0)
    users = db.scalars(query.order_by(AppUser.id).offset((page - 1) * page_size).limit(page_size)).all()
    return {
        "data": {
            "items": [user_to_dict(item) for item in users],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    }


@router.patch("/users/{user_id}")
def toggle_user(
    user_id: int, payload: ToggleUserPayload, request: Request, db: Session = Depends(get_db)
) -> dict:
    actor = _require_admin(request)
    user = _locked_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在。")
    if is_admin({"role": user.role}):
        raise HTTPException(status_code=400, detail="管理员账号受保护。")
    if user.is_active != payload.is_active:
        user.is_active, user.auth_version = payload.is_active, user.auth_version + 1
    _audit(db, request, f"用户状态变更：{user.username} active={user.is_active}", actor["username"])
    db.commit()
    return {"data": user_to_dict(user)}


@router.post("/users/{user_id}/reset-password")
def admin_reset_password(
    user_id: int, payload: ResetPasswordPayload, request: Request, db: Session = Depends(get_db)
) -> dict:
    actor = _require_admin(request)
    user = _locked_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在。")
    if is_admin({"role": user.role}):
        raise HTTPException(status_code=400, detail="管理员密码需由本人修改。")
    try:
        validate_new_password(payload.new_password, payload.confirm_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    user.password_hash, user.auth_version = hash_user_password(payload.new_password), user.auth_version + 1
    _audit(db, request, f"重置用户密码：{user.username}", actor["username"])
    db.commit()
    return {"ok": True, "message": "密码已重置，原会话已失效。"}
