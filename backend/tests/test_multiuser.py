from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.models import AppUser, DailyBriefing, HotspotEvent, HotspotRawItem
from app.core.config import settings
from app.db.session import SessionLocal, init_db
from app.main import app


init_db()
client = TestClient(app)


def _admin_headers() -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "test-admin-password"},
    )
    assert response.status_code == 200, response.text
    token = response.json()["data"]["token"]
    return {"Authorization": f"Bearer {token}", "X-Admin-Token": token}


def _register(username: str | None = None, password: str = "user-pass-123") -> tuple[dict, dict[str, str]]:
    username = username or f"user{uuid.uuid4().hex[:10]}"
    response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": password,
            "confirm_password": password,
            "display_name": "Test User",
        },
    )
    assert response.status_code == 201, response.text
    # Registration creates the account; authentication is an explicit second step.
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200, login.text
    data = login.json()["data"]
    token = data["token"]
    return data, {"Authorization": f"Bearer {token}", "X-Admin-Token": token}


def _seed_event() -> str:
    event_key = f"multiuser-test-{uuid.uuid4().hex}"
    with SessionLocal() as db:
        db.add(
            HotspotEvent(
                event_key=event_key,
                title="Multi-user isolation test event",
                summary="Public test event",
                category="AI / 大模型",
                heat_score=50,
                risk_level="LOW",
                source_codes=["github"],
                source_count=1,
                raw_item_ids=[],
            )
        )
        db.commit()
    return event_key


def test_registration_options_and_lowercase_username() -> None:
    options = client.get("/api/auth/options")
    assert options.status_code == 200, options.text
    assert options.json().get("data", {}).get("registration_enabled") is True

    suffix = uuid.uuid4().hex[:8]
    data, _headers = _register(f"CaseUser{suffix}")
    profile = data.get("profile") or data
    assert profile["username"] == f"caseuser{suffix}"
    assert profile.get("role") not in {"admin", "owner"}


def test_duplicate_usernames_are_case_insensitive_and_extras_cannot_escalate() -> None:
    username = f"dup{uuid.uuid4().hex[:9]}"
    password = "duplicate-pass"
    first = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": password,
            "confirm_password": password,
            "display_name": "First",
            "role": "admin",
            "permissions": ["system:manage"],
        },
    )
    assert first.status_code in (200, 201), first.text
    assert first.json().get("data") is None
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    assert login.status_code == 200, login.text
    assert login.json()["data"]["profile"]["role"] not in {"admin", "owner"}

    duplicate = client.post(
        "/api/auth/register",
        json={
            "username": username.upper(),
            "password": password,
            "confirm_password": password,
            "display_name": "Duplicate",
        },
    )
    assert duplicate.status_code in (400, 409, 422), duplicate.text


def test_ordinary_user_reads_public_data_but_not_admin_routes() -> None:
    _data, headers = _register()
    for path in ("/api/hotspots/events?limit=1", "/api/hotspots/briefings?limit=1"):
        response = client.get(path, headers=headers)
        assert response.status_code == 200, (path, response.text)
    for path in ("/api/system/logs", "/api/system/metrics", "/api/models/providers", "/api/knowledge/documents"):
        response = client.get(path, headers=headers)
        assert response.status_code == 403, (path, response.text)


def test_feedback_records_are_isolated_between_users() -> None:
    event_key = _seed_event()
    _alice, alice_headers = _register()
    _bob, bob_headers = _register()

    created = client.post(
        f"/api/hotspots/events/{event_key}/feedback",
        json={"action": "USEFUL", "note": "alice note"},
        headers=alice_headers,
    )
    assert created.status_code == 200, created.text
    assert client.get("/api/hotspots/feedback", headers=alice_headers).json()["data"]["items"]
    assert client.get("/api/hotspots/feedback", headers=bob_headers).json()["data"]["items"] == []
    assert client.get(f"/api/hotspots/events/{event_key}/feedback", headers=bob_headers).json()["data"] == []

    bob_block = client.post(
        f"/api/hotspots/events/{event_key}/feedback",
        json={"action": "BLOCK", "note": "bob block"},
        headers=bob_headers,
    )
    assert bob_block.status_code == 200, bob_block.text
    assert len(client.get(f"/api/hotspots/events/{event_key}/feedback", headers=alice_headers).json()["data"]) == 1
    assert len(client.get(f"/api/hotspots/events/{event_key}/feedback", headers=bob_headers).json()["data"]) == 1

    # A user cannot delete another user's feedback by reusing the event key.
    removed = client.delete(f"/api/hotspots/events/{event_key}/feedback/BLOCK", headers=alice_headers)
    assert removed.status_code == 200
    assert len(client.get(f"/api/hotspots/events/{event_key}/feedback", headers=bob_headers).json()["data"]) == 1


def test_admin_can_disable_user_and_reset_password_revokes_sessions() -> None:
    username = f"managed{uuid.uuid4().hex[:9]}"
    old_password = "old-password-1"
    new_password = "new-password-2"
    registered, user_headers = _register(username, old_password)
    profile = registered.get("profile") or registered
    user_id = profile.get("id") or registered.get("id")
    assert user_id is not None
    admin_headers = _admin_headers()

    reset = client.post(
        f"/api/auth/users/{user_id}/reset-password",
        json={"new_password": new_password, "confirm_password": new_password},
        headers=admin_headers,
    )
    assert reset.status_code == 200, reset.text
    assert client.get("/api/auth/me", headers=user_headers).status_code == 401
    old_login = client.post("/api/auth/login", json={"username": username, "password": old_password})
    assert old_login.status_code == 401
    new_login = client.post("/api/auth/login", json={"username": username, "password": new_password})
    assert new_login.status_code == 200, new_login.text

    disabled = client.patch(
        f"/api/auth/users/{user_id}",
        json={"is_active": False},
        headers=admin_headers,
    )
    assert disabled.status_code == 200, disabled.text
    fresh_token = new_login.json()["data"]["token"]
    fresh_headers = {"Authorization": f"Bearer {fresh_token}", "X-Admin-Token": fresh_token}
    assert client.get("/api/auth/me", headers=fresh_headers).status_code == 401
    disabled_login = client.post("/api/auth/login", json={"username": username, "password": new_password})
    assert disabled_login.status_code in (401, 403)

    reenabled = client.patch(
        f"/api/auth/users/{user_id}",
        json={"is_active": True},
        headers=admin_headers,
    )
    assert reenabled.status_code == 200, reenabled.text


@pytest.mark.parametrize("password", ["short", "a" * 73, "é" * 40])
def test_registration_rejects_invalid_passwords(password: str) -> None:
    username = f"pw{uuid.uuid4().hex[:10]}"
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": password, "confirm_password": password},
    )
    assert response.status_code in (400, 422), response.text


def test_profile_and_password_are_persistent_and_old_sessions_stay_revoked() -> None:
    data, headers = _register()
    username = data["profile"]["username"]
    assert client.put('/api/auth/profile', headers=headers, json={'display_name': 'Updated Name'}).status_code == 200
    with SessionLocal() as db:
        assert db.get(AppUser, data['profile']['id']).display_name == 'Updated Name'
    response = client.post('/api/auth/change-password', headers=headers, json={
        'old_password': 'user-pass-123', 'new_password': 'replacement-pass', 'confirm_password': 'replacement-pass',
    })
    assert response.status_code == 200, response.text
    assert client.get('/api/auth/me', headers=headers).status_code == 401
    assert client.post('/api/auth/login', json={'username': username, 'password': 'user-pass-123'}).status_code == 401
    assert client.post('/api/auth/login', json={'username': username, 'password': 'replacement-pass'}).status_code == 200


def test_registration_switch_and_reserved_account(monkeypatch) -> None:
    from dataclasses import replace
    from app.api import auth
    payload = {'username': 'admin', 'password': 'password123', 'confirm_password': 'password123'}
    assert client.post('/api/auth/register', json=payload).status_code == 409
    monkeypatch.setattr(auth, 'settings', replace(settings, registration_enabled=False))
    assert not client.get('/api/auth/options').json()['data']['registration_enabled']
    assert client.post('/api/auth/register', json=payload).status_code == 403
    monkeypatch.setattr(auth, 'settings', replace(settings, registration_enabled=True, api_auth_enabled=False))
    assert not client.get('/api/auth/options').json()['data']['registration_enabled']
    assert client.post('/api/auth/register', json=payload).status_code == 403


def test_user_management_requires_admin_and_protects_owner() -> None:
    data, headers = _register()
    owner_headers = _admin_headers()
    owner_id = client.get('/api/auth/me', headers=owner_headers).json()['data']['id']
    for method, path, body in [
        ('GET', '/api/auth/users', None),
        ('PATCH', f"/api/auth/users/{data['profile']['id']}", {'is_active': False}),
        ('POST', f"/api/auth/users/{data['profile']['id']}/reset-password", {'new_password': 'password123', 'confirm_password': 'password123'}),
        ('POST', '/api/hotspots/briefings/generate-async', {}),
        ('GET', '/api/knowledge/health', None),
        ('GET', '/api/hotspots/sources/health?live=true', None),
    ]:
        assert client.request(method, path, json=body, headers=headers).status_code == 403
    assert client.patch(f'/api/auth/users/{owner_id}', headers=owner_headers, json={'is_active': False}).status_code == 400
    found = client.get('/api/auth/users', params={'keyword': data['profile']['username']}, headers=owner_headers)
    assert found.json()['data']['total'] == 1
    assert 'password_hash' not in found.text
    assert 'auth_version' not in found.text


def test_member_responses_exclude_private_context_and_blocks_are_personal() -> None:
    from datetime import date
    from app.api.hotspots import event_to_dict
    key = f'ai-private-{uuid.uuid4().hex}'
    sentinel = 'PRIVATE_KNOWLEDGE_SENTINEL'
    day = date(2097, 1, 5)
    with SessionLocal() as db:
        raw = HotspotRawItem(source_code='github', source_name='GitHub', title='AI model repository',
                             url='https://github.com/example/ai-model', content='Public model release', raw_payload={'internal': sentinel})
        db.add(raw)
        db.flush()
        event = HotspotEvent(event_key=key, title=raw.title, source_codes=['github'], source_count=1,
                             raw_item_ids=[raw.id], summary=sentinel, heat_score=100, category='AI / 大模型',
                             rag_references=[{'preview': sentinel}], analysis_error=sentinel,
                             main_opinions=[sentinel], business_relevance_reason=sentinel)
        db.add(event)
        db.flush()
        from fastapi.encoders import jsonable_encoder
        payload = jsonable_encoder(event_to_dict(db, event))
        db.add(DailyBriefing(briefing_date=day, title=sentinel, summary=sentinel, markdown=sentinel,
                            raw_json={'events': [payload], 'source_health': {'error': sentinel}}))
        db.commit()
    _, alice = _register()
    _, bob = _register()
    try:
        response = client.get('/api/hotspots/events?limit=500', headers=alice)
        assert response.status_code == 200, response.text
        assert key in response.text
        assert sentinel not in response.text
        for path in ['/api/hotspots/briefings', f'/api/hotspots/briefings/{day}']:
            response = client.get(path, headers=alice)
            assert response.status_code == 200, response.text
            assert sentinel not in response.text
        assert client.post(f'/api/hotspots/events/{key}/feedback', headers=alice, json={'action': 'BLOCK'}).status_code == 200
        assert key not in client.get('/api/hotspots/events?limit=500', headers=alice).text
        assert key in client.get('/api/hotspots/events?limit=500', headers=bob).text
        owner = _admin_headers()
        assert sentinel in client.get(f'/api/hotspots/briefings/{day}', headers=owner).text
    finally:
        with SessionLocal() as db:
            from sqlalchemy import delete
            db.execute(delete(DailyBriefing).where(DailyBriefing.briefing_date == day))
            db.commit()


def test_reenable_does_not_restore_old_session() -> None:
    data, headers = _register()
    owner = _admin_headers()
    path = f"/api/auth/users/{data['profile']['id']}"
    assert client.patch(path, headers=owner, json={'is_active': False}).status_code == 200
    assert client.patch(path, headers=owner, json={'is_active': True}).status_code == 200
    assert client.get('/api/auth/me', headers=headers).status_code == 401


def test_public_auth_rate_limit_ignores_forged_tokens(monkeypatch) -> None:
    from app.services import session_service
    captured = []
    def rate_limit(**kwargs):
        captured.append(kwargs['token'])
        return False, 60
    monkeypatch.setattr(session_service, 'check_rate_limit', rate_limit)
    for token in ('forged-one', 'forged-two'):
        result = client.post('/api/auth/register', headers={'X-Admin-Token': token}, json={})
        assert result.status_code == 429
    assert captured == ['public-auth', 'public-auth']
