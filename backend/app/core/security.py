"""轻量安全中间件与密钥工具。"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re

import bcrypt
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.concurrency import run_in_threadpool

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token 提取与校验
# ---------------------------------------------------------------------------


def extract_admin_token(request: Request) -> str:
    """从请求头中提取管理员令牌。

    P0-5: 已移除 URL query param 通道，避免 token 泄露到日志/Referer/浏览器历史。
    支持 Authorization: Bearer <token> 和 X-Admin-Token 两种 Header。
    """
    explicit = request.headers.get("X-Admin-Token")
    if explicit:
        return explicit.strip()
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def resolve_token_principal(token: str) -> dict | None:
    """Validate session state against its persistent identity on every request."""
    if not token:
        return None
    expected = settings.admin_token or ""
    if expected and hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
        return _service_principal("service_token")
    try:
        from app.services.session_service import get_session
        from app.services.user_service import user_principal
        from app.db.models import AppUser
        from app.db.session import SessionLocal

        session = get_session(token)
        if session is None or "user_id" not in session or "auth_version" not in session:
            return None
        with SessionLocal() as db:
            user = db.get(AppUser, int(session["user_id"]))
            if user is None or not user.is_active or user.auth_version != int(session["auth_version"]):
                return None
            return user_principal(user)
    except Exception:  # noqa: BLE001
        logger.warning("Session identity verification failed", exc_info=True)
        return None


def _service_principal(auth_mode: str) -> dict:
    return {
        "id": None, "username": settings.admin_username.strip().lower(),
        "display_name": settings.admin_display_name or settings.admin_username,
        "role": "owner", "is_active": True, "auth_mode": auth_mode,
    }


def is_admin(principal: dict) -> bool:
    return principal.get("role") in {"owner", "admin"}


def get_current_principal(request: Request) -> dict:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="请先登录。")
    return principal


def valid_admin_token(token: str) -> bool:
    principal = resolve_token_principal(token)
    return principal is not None and is_admin(principal)


def _member_route_allowed(path: str, method: str) -> bool:
    self_routes = {
        ("GET", "/auth/me"), ("POST", "/auth/logout"),
        ("POST", "/auth/change-password"), ("PUT", "/auth/profile"),
        ("POST", "/auth/reset-failures"),
    }
    if (method, path) in self_routes:
        return True
    if method == "GET" and path in {
        "/hotspots/events", "/hotspots/feedback", "/hotspots/briefings",
        "/hotspots/briefings/today",
    }:
        return True
    if method == "GET" and re.fullmatch(r"/hotspots/briefings/\d{4}-\d{2}-\d{2}", path):
        return True
    if method in {"GET", "POST"} and re.fullmatch(r"/hotspots/events/[^/]+/feedback", path):
        return True
    return method == "DELETE" and re.fullmatch(r"/hotspots/events/[^/]+/feedback/[^/]+", path) is not None


def valid_admin_password(password: str) -> bool:
    """校验管理员密码。

    P0-7: 优先使用 bcrypt 校验；兼容已部署环境的 SHA256 摘要。
    明文密码已移除，不再支持。
    """
    raw = (password or "").encode("utf-8")

    # 1. 优先 bcrypt
    bcrypt_hash = settings.admin_password_bcrypt.strip()
    if bcrypt_hash:
        try:
            return bcrypt.checkpw(raw, bcrypt_hash.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            logger.warning("bcrypt 密码校验异常: %s", exc)
            return False

    # 2. 兼容已部署环境的 SHA256（已弃用，建议迁移到 bcrypt）
    sha256_hash = settings.admin_password_sha256.strip()
    if sha256_hash:
        digest = hashlib.sha256(raw).hexdigest()
        return hmac.compare_digest(digest, sha256_hash)

    return False


def hash_password_bcrypt(password: str) -> str:
    """使用 bcrypt 生成密码哈希，供运维人员通过脚本生成 ADMIN_PASSWORD_BCRYPT。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def resolve_client_ip(request: Request) -> str:
    """根据可信代理层数解析客户端 IP，避免任意 XFF 绕过登录保护。"""
    fallback = request.client.host if request.client else "unknown"
    proxy_count = max(0, settings.trusted_proxy_count)
    if proxy_count == 0:
        return fallback

    forwarded = request.headers.get("x-forwarded-for", "")
    parts = [item.strip() for item in forwarded.split(",") if item.strip()]
    if not parts:
        return fallback

    idx = max(0, len(parts) - proxy_count)
    return parts[idx]


# ---------------------------------------------------------------------------
# 限流（P0-2: 迁移到 Redis）
# ---------------------------------------------------------------------------


class AdminAuthAndRateLimitMiddleware(BaseHTTPMiddleware):
    """保护管理 API，并对高成本操作做基础限流。

    - 所有 /api 路由默认要求会话 token 或静态 ADMIN_TOKEN。
    - OPTIONS 和显式豁免路径跳过，保证 CORS 预检和系统状态正常。
    - P0-2: 限流计数迁移到 Redis，多 worker/多实例共享。
    """

    def __init__(self, app, *, api_prefix: str = "/api") -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.api_prefix = api_prefix.rstrip("/") or "/api"

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        path = request.url.path.rstrip("/") or "/"
        if not (path == self.api_prefix or path.startswith(self.api_prefix + "/")) or request.method.upper() == "OPTIONS":
            return await call_next(request)
        auth_exempt = path in settings.auth_exempt_paths

        if settings.api_auth_enabled and not auth_exempt:
            token = extract_admin_token(request)
            principal = await run_in_threadpool(resolve_token_principal, token)
            if principal is None:
                return JSONResponse(
                    status_code=401,
                    content={
                        "detail": "请先登录，或在请求头中设置有效的会话凭据。",
                        "code": "ADMIN_TOKEN_REQUIRED",
                    },
                )
            request.state.principal = principal
            if not is_admin(principal) and not _member_route_allowed(path[len(self.api_prefix):], request.method.upper()):
                return JSONResponse(status_code=403, content={"detail": "此操作仅限管理员。", "code": "ADMIN_REQUIRED"})
        elif not settings.api_auth_enabled:
            request.state.principal = _service_principal("development")

        if settings.rate_limit_enabled:
            rate_response = await run_in_threadpool(self._check_rate_limit, request)
            if rate_response is not None:
                return rate_response

        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @staticmethod
    def _client_ip(request: Request) -> str:
        return resolve_client_ip(request)

    @staticmethod
    def _check_rate_limit(request: Request) -> JSONResponse | None:
        """P0-2: 使用 Redis 滑动窗口限流。"""
        from app.services.session_service import check_rate_limit

        is_write = request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
        token = extract_admin_token(request) or "anonymous"
        if request.url.path.rstrip("/") in {
            settings.api_prefix + "/auth/login", settings.api_prefix + "/auth/register",
        }:
            token = "public-auth"
        client_host = AdminAuthAndRateLimitMiddleware._client_ip(request)

        try:
            allowed, retry_after = check_rate_limit(
                client_ip=client_host,
                token=token,
                is_write=is_write,
            )
        except Exception as exc:  # noqa: BLE001
            # 安全组件应 fail-closed 或至少告警，而非静默放行。
            # Redis 抖动时若直接放行，限流完全失效，高成本接口可被无限刷。
            logger.warning(
                "限流依赖的 Redis 不可用: %s (rate_limit_fail_open=%s)",
                exc,
                settings.rate_limit_fail_open,
                exc_info=True,
            )
            if settings.rate_limit_fail_open:
                return None
            return JSONResponse(
                status_code=503,
                headers={"Retry-After": "5"},
                content={
                    "detail": "限流服务暂时不可用，请稍后重试。",
                    "code": "RATE_LIMITER_UNAVAILABLE",
                },
            )

        if not allowed:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={
                    "detail": f"请求过于频繁，请 {retry_after} 秒后再试。",
                    "code": "RATE_LIMITED",
                },
            )
        return None
