"""密码哈希生成工具。

P0-7: 生成 bcrypt 密码哈希，供运维人员配置 ADMIN_PASSWORD_BCRYPT 环境变量。

用法：
    python scripts/hash_password.py
    python scripts/hash_password.py "my-strong-password"
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bcrypt


def main() -> None:
    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        password = getpass.getpass("请输入要哈希的管理员密码：")
        confirm = getpass.getpass("请再次输入确认：")
        if password != confirm:
            print("两次输入不一致，已退出。")
            sys.exit(1)

    if len(password) < 8:
        print("警告：密码长度不足 8 位，建议使用更长的密码。", file=sys.stderr)

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    print("\n=== bcrypt 密码哈希 ===")
    print(hashed)
    print("\n请将此值设置到 .env 文件的 ADMIN_PASSWORD_BCRYPT：")
    print(f"ADMIN_PASSWORD_BCRYPT='{hashed}'")
    print("\n注意：明文密码 ADMIN_PASSWORD 已不再支持，请勿使用。")


if __name__ == "__main__":
    main()
