"""Check staged source for private files and likely credentials; never print values."""
from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DIRECTORIES = {".venv", "node_modules", ".runtime", ".idea", ".kombai", ".playwright-cli",
                       "output", "reports", "__pycache__", ".pytest_cache", "dist", "coverage", "htmlcov"}
PRIVATE_SUFFIXES = (".local.json", ".local.yml", ".local.yaml", ".sql", ".sql.gz", ".sqlite", ".sqlite3",
                    ".db", ".pem", ".key", ".p12", ".pfx", ".log", ".bak")
PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "api-key": re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b"),
}
REVIEWED_BINARY_PREFIXES = ("docs/screenshots/",)
REVIEWED_BINARY_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def reviewed_binary_path(path: str) -> bool:
    normalized = PurePosixPath(path).as_posix().lower()
    return normalized.startswith(REVIEWED_BINARY_PREFIXES) and normalized.endswith(REVIEWED_BINARY_SUFFIXES)


def private_path(path: str) -> bool:
    value = PurePosixPath(path)
    name = value.name.lower()
    return (bool(set(value.parts) & PRIVATE_DIRECTORIES)
            or (name.startswith(".env") and name != ".env.example")
            or name.endswith(PRIVATE_SUFFIXES) or name == "test_full_output.txt")


def inspect_text(path: str, text: str, known_secrets=()) -> list[tuple[int, str]]:
    hits = []
    for line_number, line in enumerate(text.splitlines(), 1):
        for rule, pattern in PATTERNS.items():
            for match in pattern.finditer(line):
                if not re.match(r"sk-(?:test|unit|e2e|dummy|example|placeholder)-", match.group()):
                    hits.append((line_number, rule))
        if any(secret in line for secret in known_secrets):
            hits.append((line_number, "local-credential-copy"))
    return hits


def local_secrets():
    path = ROOT / ".env"
    if not path.exists():
        return []
    values = []
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        value = value.strip().strip("'\"")
        if separator and re.search(r"KEY|TOKEN|SECRET|PASSWORD", key.upper()) and len(value) >= 16:
            values.append(value)
    return values


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", action="store_true", help="Also inspect untracked, non-ignored source files")
    args = parser.parse_args()
    arguments = ["ls-files", "-z", "--cached"]
    if args.worktree:
        arguments += ["--others", "--exclude-standard"]
    paths = sorted(set(path for path in git(*arguments).decode("utf-8").split("\0") if path))
    if not paths:
        raise SystemExit("No source files selected; stage reviewed files or use --worktree")
    findings = []
    secrets = local_secrets()
    for path in paths:
        if private_path(path):
            findings.append(f"{path}: private-file")
            continue
        if args.worktree and not (ROOT / path).exists():
            continue
        data = (ROOT / path).read_bytes() if args.worktree else git("show", f":{path}")
        if b"\0" in data:
            if not reviewed_binary_path(path):
                findings.append(f"{path}: binary-requires-manual-review")
            continue
        for line, rule in inspect_text(path, data.decode("utf-8", errors="replace"), secrets):
            findings.append(f"{path}:{line}: {rule}")
    for finding in findings:
        print(finding)
    print(f"Reviewed {len(paths)} source files; findings: {len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
