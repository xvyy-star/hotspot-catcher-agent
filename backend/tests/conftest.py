from __future__ import annotations

import os
import tempfile
from pathlib import Path

import bcrypt
import redis
import fakeredis
import pytest
import requests
from sqlalchemy import BigInteger
from sqlalchemy.ext.compiler import compiles


_test_directory = tempfile.TemporaryDirectory(prefix="hotspot-pytest-")
_database_path = Path(_test_directory.name) / "tests.sqlite3"
# Set before app imports, including test collection and init_db() in smoke tests.
os.environ["DATABASE_URL"] = "sqlite:///" + _database_path.as_posix()
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"
for key in ("AI_API_KEY", "EMBEDDING_API_KEY", "EMBEDDING_BASE_URL"):
    os.environ[key] = ""
os.environ["HOTSPOT_PUSH_ENABLED"] = "false"
os.environ["RATE_LIMIT_WRITE_PER_WINDOW"] = "1000"


@compiles(BigInteger, "sqlite")
def _sqlite_primary_key(type_, compiler, **kwargs):
    # SQLite autoincrement requires exactly INTEGER, unlike MySQL BIGINT.
    return "INTEGER"


# 在任何 app 模块导入前固定测试安全配置，避免测试收集顺序受到本地 .env 影响。
os.environ["API_AUTH_ENABLED"] = "true"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["APP_SECRET_KEY"] = "test-secret-key-for-unit-test-only"
os.environ["ADMIN_PASSWORD_BCRYPT"] = bcrypt.hashpw(
    b"test-admin-password", bcrypt.gensalt(rounds=4)
).decode("utf-8")
os.environ["ADMIN_PASSWORD_SHA256"] = ""
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["AUTO_CREATE_TABLES"] = "true"
os.environ["DOCS_ENABLED"] = "false"
os.environ["TRUSTED_PROXY_COUNT"] = "0"


@pytest.fixture(autouse=True)
def isolated_external_services(monkeypatch):
    server = fakeredis.FakeServer()

    def fake_redis(*args, **kwargs):
        return fakeredis.FakeRedis(server=server, decode_responses=kwargs.get("decode_responses", False))

    monkeypatch.setattr(redis, "from_url", fake_redis)
    monkeypatch.setattr(redis.Redis, "from_url", fake_redis)
    from app.services import session_service
    monkeypatch.setattr(session_service, "_client", None)

    def no_external_http(*args, **kwargs):
        raise requests.ConnectionError("External HTTP is disabled in tests; mock the request")

    monkeypatch.setattr(requests.sessions.Session, "request", no_external_http)


def pytest_sessionfinish(session, exitstatus) -> None:  # type: ignore[no-untyped-def]
    del session, exitstatus
    from app.db.session import engine
    engine.dispose()
    _test_directory.cleanup()
