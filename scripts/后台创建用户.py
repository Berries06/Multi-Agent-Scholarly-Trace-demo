"""由服务器管理员创建账号；产品端不提供公开注册入口。"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from yanhai.resources import database_path  # noqa: E402
from yanhai.storage import AppRepository  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="创建研海寻踪产品账号")
    parser.add_argument("--email", required=True, help="登录邮箱")
    parser.add_argument("--nickname", required=True, help="用户昵称")
    parser.add_argument("--password", help="密码；省略时安全交互输入")
    args = parser.parse_args()
    password = args.password or getpass.getpass("密码（至少 8 位）：")
    user = AppRepository(database_path()).register_user(
        args.email,
        args.nickname,
        password,
    )
    print(f"已创建账号：{user['nickname']} <{user['email']}> ({user['user_id']})")


if __name__ == "__main__":
    main()
