"""基于 Redis 的会话管理、限流与登录锁定服务。

设计目标：
1. 会话 token 登录后签发，存入 Redis，支持主动吊销（logout）。
2. 限流计数跨 worker/实例共享，避免多进程内存计数被绕过。
3. 登录失败锁定同样跨实例生效。
"""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta
from typing import Any

import redis

from app.core.config import settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """获取 Redis 客户端单例。"""
    global _client
    if _client is None:
        _client = redis.from_url(
            settings.redis_url,
            socket_connect_timeout=3,
            socket_timeout=3,
            decode_responses=True,
        )
    return _client


# ---------------------------------------------------------------------------
# 会话管理
# ---------------------------------------------------------------------------

_SESSION_PREFIX = "hotspot:session:"
def create_session(*, username: str, ip: str, remember: bool = False) -> tuple[str, int]:
    """签发一个新的会话 token，写入 Redis，返回 (token, ttl_seconds)。"""
    token = secrets.token_urlsafe(48)
    configured_ttl = settings.session_remember_ttl_seconds if remember else settings.session_ttl_seconds
    ttl = max(60, int(configured_ttl))
    payload: dict[str, Any] = {
        "username": username,
        "ip": ip,
        "created_at": datetime.utcnow().isoformat(),
        "remember": "1" if remember else "0",
    }
    client = get_redis()
    client.hset(_SESSION_PREFIX + token, mapping=payload)
    client.expire(_SESSION_PREFIX + token, ttl)
    return token, ttl


def get_session(token: str) -> dict[str, str] | None:
    """查询会话是否存在，返回会话信息或 None。"""
    if not token:
        return None
    client = get_redis()
    data = client.hgetall(_SESSION_PREFIX + token)
    if not data:
        return None
    return data


def revoke_session(token: str) -> bool:
    """吊销会话，返回是否确实删除了一条。"""
    if not token:
        return False
    client = get_redis()
    deleted = client.delete(_SESSION_PREFIX + token)
    return bool(deleted)


def revoke_all_sessions(username: str | None = None) -> int:
    """吊销全部（或指定用户的）会话，返回删除数量。"""
    client = get_redis()
    count = 0
    for key in client.scan_iter(_SESSION_PREFIX + "*"):
        if username:
            data = client.hgetall(key)
            if data.get("username") != username:
                continue
        client.delete(key)
        count += 1
    return count


# ---------------------------------------------------------------------------
# 限流
# ---------------------------------------------------------------------------

_RATE_PREFIX = "hotspot:rate:"


def check_rate_limit(
    *,
    client_ip: str,
    token: str,
    is_write: bool,
) -> tuple[bool, int]:
    """滑动窗口限流（Redis INCR + EXPIRE）。

    返回 (allowed, retry_after_seconds)。
    """
    limit = settings.rate_limit_write_per_window if is_write else settings.rate_limit_read_per_window
    window = max(1, settings.rate_limit_window_seconds)
    bucket_key = f"{_RATE_PREFIX}{client_ip}:{token[:16]}:{'w' if is_write else 'r'}:{int(time.time() // window)}"
    client = get_redis()
    # 不在此处吞掉 Redis 异常：由调用方（限流中间件）根据 rate_limit_fail_open 决定
    # 是 fail-closed（拒绝）还是放行，避免限流静默失效。
    current = client.incr(bucket_key)
    if current == 1:
        client.expire(bucket_key, window)
    if current > limit:
        retry_after = max(1, window - int(time.time()) % window)
        return False, retry_after
    return True, 0


# ---------------------------------------------------------------------------
# 登录失败锁定
# ---------------------------------------------------------------------------

_LOGIN_FAIL_PREFIX = "hotspot:login_fail:"
_LOCK_PREFIX = "hotspot:login_lock:"


def record_login_failure(username: str, ip: str) -> tuple[int, bool, int]:
    """记录一次登录失败，返回 (failed_count, is_locked, lock_seconds)。"""
    client = get_redis()
    fail_key = f"{_LOGIN_FAIL_PREFIX}{username.lower()}:{ip}"
    lock_key = f"{_LOCK_PREFIX}{username.lower()}:{ip}"
    try:
        count = client.incr(fail_key)
        client.expire(fail_key, max(settings.login_lock_seconds * 2, 3600))
        limit = max(1, settings.login_failure_limit)
        if count >= limit:
            lock_ttl = max(1, settings.login_lock_seconds)
            client.set(lock_key, "1", ex=lock_ttl)
            return count, True, lock_ttl
        return count, False, 0
    except Exception:  # noqa: BLE001
        return 0, False, 0


def is_login_locked(username: str, ip: str) -> tuple[bool, int]:
    """检查是否被锁定，返回 (is_locked, retry_after_seconds)。"""
    client = get_redis()
    lock_key = f"{_LOCK_PREFIX}{username.lower()}:{ip}"
    try:
        ttl = client.ttl(lock_key)
        if ttl and ttl > 0:
            return True, ttl
        return False, 0
    except Exception:  # noqa: BLE001
        return False, 0


def reset_login_failures(username: str, ip: str) -> None:
    """登录成功后清除失败计数和锁定。"""
    client = get_redis()
    try:
        client.delete(f"{_LOGIN_FAIL_PREFIX}{username.lower()}:{ip}")
        client.delete(f"{_LOCK_PREFIX}{username.lower()}:{ip}")
    except Exception:  # noqa: BLE001
        pass


def get_login_state(username: str, ip: str) -> dict[str, Any]:
    """读取当前登录安全状态快照。"""
    client = get_redis()
    fail_key = f"{_LOGIN_FAIL_PREFIX}{username.lower()}:{ip}"
    lock_key = f"{_LOCK_PREFIX}{username.lower()}:{ip}"
    try:
        failed_count = int(client.get(fail_key) or 0)
        lock_ttl = client.ttl(lock_key)
        locked_until = (datetime.utcnow() + timedelta(seconds=lock_ttl)).isoformat() if lock_ttl and lock_ttl > 0 else None
        return {
            "failed_count": failed_count,
            "locked_until": locked_until,
            "is_locked": bool(lock_ttl and lock_ttl > 0),
        }
    except Exception:  # noqa: BLE001
        return {"failed_count": 0, "locked_until": None, "is_locked": False}
