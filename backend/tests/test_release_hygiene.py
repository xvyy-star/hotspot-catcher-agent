import importlib.util

from app.core.config import PROJECT_ROOT

spec = importlib.util.spec_from_file_location("release_check", PROJECT_ROOT / "scripts/check_public_release.py")
release_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_check)


def test_private_release_paths_are_blocked():
    for path in [".env", "frontend/.env.production", "config/push.local.json", "reports/report.json",
                 "output/backup.sql", "keys/server.pem", "backend/__pycache__/main.pyc"]:
        assert release_check.private_path(path)
    for path in [".env.example", "frontend/.env.example", "backend/app/main.py"]:
        assert not release_check.private_path(path)


def test_release_scan_reports_rules_not_values():
    token = "ghp_" + "A" * 36
    findings = release_check.inspect_text("source.py", f'token = "{token}"')
    assert findings == [(1, "github-token")]
    assert token not in str(findings)
    assert release_check.inspect_text("source.py", "copied-local-credential", ["copied-local-credential"])


def test_no_model_provider_is_created_without_configuration(monkeypatch):
    from app.services import model_provider_service as service
    from app.db.session import SessionLocal
    from app.db.models import AIModelProvider
    from sqlalchemy import select
    from types import SimpleNamespace
    monkeypatch.setattr(service, "settings", SimpleNamespace(ai_base_url="", ai_model="", ai_api_key=""))
    with SessionLocal() as db:
        before = list(db.scalars(select(AIModelProvider.id)))
        service.ensure_default_providers(db)
        assert list(db.scalars(select(AIModelProvider.id))) == before
