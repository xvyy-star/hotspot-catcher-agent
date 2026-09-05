"""Initialize local-only credentials without overwriting an existing .env."""
from __future__ import annotations

from getpass import getpass
from pathlib import Path
import secrets

import bcrypt

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = ROOT / ".env"
    if destination.exists():
        print("Existing .env retained. No credentials were changed.")
        return
    password = getpass("Choose an administrator password (at least 12 characters): ")
    if len(password) < 12 or password != getpass("Repeat the administrator password: "):
        raise SystemExit("Password confirmation failed or password is too short.")
    database_password = secrets.token_hex(24)
    replacements = {
        "ADMIN_PASSWORD_BCRYPT": "'" + bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode() + "'",
        "ADMIN_TOKEN": secrets.token_hex(32),
        "APP_SECRET_KEY": secrets.token_hex(32),
        "MYSQL_ROOT_PASSWORD": secrets.token_hex(24),
        "MYSQL_PASSWORD": database_password,
        "DATABASE_URL": f"mysql+pymysql://hotspot:{database_password}@localhost:3307/hotspot_agent?charset=utf8mb4",
    }
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        key, separator, _ = line.partition("=")
        if separator and key.strip() in replacements:
            lines[index] = f"{key.strip()}={replacements[key.strip()]}"
    with destination.open("x", encoding="utf-8") as output:
        output.write("\n".join(lines) + "\n")
    print("Local .env created. Secrets were not printed; keep this file private.")


if __name__ == "__main__":
    main()
