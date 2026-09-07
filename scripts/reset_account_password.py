"""Local account recovery; password input stays off the command line and logs."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select
from app.db.models import AppUser
from app.db.session import SessionLocal
from app.services.user_service import hash_user_password, normalize_username, validate_new_password
from app.services.system_log_service import write_system_log


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username")
    args = parser.parse_args()
    password = getpass.getpass("New password: ")
    confirmation = getpass.getpass("Confirm password: ")
    validate_new_password(password, confirmation)
    with SessionLocal() as db:
        user = db.scalar(
            select(AppUser).where(AppUser.username == normalize_username(args.username)).with_for_update()
        )
        if user is None:
            raise SystemExit("Account not found; run database migrations and start the application first.")
        user.password_hash = hash_user_password(password)
        user.auth_version += 1
        write_system_log(
            db,
            level="WARNING",
            module="auth",
            message="Local account password recovery",
            extra={"username": user.username},
        )
        db.commit()
    print("Password updated. Previous sessions are invalid.")


if __name__ == "__main__":
    main()
