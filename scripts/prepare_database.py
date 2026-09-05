"""Bootstrap a legacy database once, then apply all Alembic migrations."""
from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db import models  # noqa: E402,F401
from app.db.session import Base, engine  # noqa: E402


def _current_revision() -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def prepare_database() -> str:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    before = _current_revision()
    existing_tables = set(inspect(engine).get_table_names())
    required_tables = {"hotspot_event", "ai_model_provider", "llm_call_log"}

    if before is None or not required_tables.issubset(existing_tables):
        # Databases created before Alembic have the application tables but no
        # revision marker. create_all only fills missing whole tables; the
        # idempotent migration chain remains responsible for column changes.
        Base.metadata.create_all(bind=engine)

    command.upgrade(config, "head")
    current = _current_revision()
    expected = ScriptDirectory.from_config(config).get_current_head()
    if not current or current != expected:
        raise RuntimeError(f"database revision mismatch: current={current!r}, expected={expected!r}")
    return current


def main() -> int:
    revision = prepare_database()
    print(f"Database ready at Alembic revision {revision}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
