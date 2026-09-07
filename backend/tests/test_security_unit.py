from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import security  # noqa: E402
from app.services import briefing_task_service, session_service  # noqa: E402


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.expirations: dict[str, int] = {}

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None):
        if nx and key in self.values:
            return None
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex
        return True

    def get(self, key: str):
        return self.values.get(key)

    def hset(self, key: str, *, mapping: dict[str, str]):
        self.hashes[key] = mapping

    def expire(self, key: str, ttl: int):
        self.expirations[key] = ttl
        return True

    def eval(self, _script: str, _key_count: int, key: str, expected: str):
        if self.values.get(key) != expected:
            return 0
        del self.values[key]
        return 1


def request_with_ip(host: str, forwarded_for: str = "") -> SimpleNamespace:
    headers = {"x-forwarded-for": forwarded_for} if forwarded_for else {}
    return SimpleNamespace(client=SimpleNamespace(host=host), headers=headers)


def test_direct_request_ignores_spoofed_forwarded_for(monkeypatch) -> None:
    monkeypatch.setattr(security, "settings", SimpleNamespace(trusted_proxy_count=0))
    request = request_with_ip("127.0.0.1", "203.0.113.99")

    assert security.resolve_client_ip(request) == "127.0.0.1"


def test_trusted_proxy_uses_address_before_trusted_hop(monkeypatch) -> None:
    monkeypatch.setattr(security, "settings", SimpleNamespace(trusted_proxy_count=1))
    request = request_with_ip("10.0.0.8", "203.0.113.99, 198.51.100.42")

    assert security.resolve_client_ip(request) == "198.51.100.42"


def test_session_ttl_uses_runtime_configuration(monkeypatch) -> None:
    from fakeredis import FakeRedis as RedisFixture
    fake = RedisFixture(decode_responses=True)
    monkeypatch.setattr(session_service, "get_redis", lambda: fake)
    monkeypatch.setattr(
        session_service,
        "settings",
        SimpleNamespace(session_ttl_seconds=1234, session_remember_ttl_seconds=5678),
    )

    token, ttl = session_service.create_session(username="admin", ip="127.0.0.1")
    remember_token, remember_ttl = session_service.create_session(
        username="admin", ip="127.0.0.1", remember=True
    )

    assert ttl == 1234
    assert remember_ttl == 5678
    assert fake.ttl(f"hotspot:session:{token}") == 1234
    assert fake.ttl(f"hotspot:session:{remember_token}") == 5678


def test_briefing_generation_slot_prevents_duplicate_work(monkeypatch) -> None:
    fake = FakeRedis()
    monkeypatch.setattr(briefing_task_service, "get_redis", lambda: fake)
    monkeypatch.setattr(
        briefing_task_service,
        "settings",
        SimpleNamespace(briefing_task_lock_seconds=3600),
    )
    target_date = date(2026, 7, 10)

    first_claimed, first_existing = briefing_task_service._claim_generation_slot(
        target_date, "run-first"
    )
    second_claimed, second_existing = briefing_task_service._claim_generation_slot(
        target_date, "run-second"
    )

    assert first_claimed is True
    assert first_existing is None
    assert second_claimed is False
    assert second_existing == "run-first"

    briefing_task_service._release_generation_slot(target_date, "run-second")
    assert fake.get(briefing_task_service._slot_key(target_date)) == "run-first"

    briefing_task_service._release_generation_slot(target_date, "run-first")
    assert fake.get(briefing_task_service._slot_key(target_date)) is None
