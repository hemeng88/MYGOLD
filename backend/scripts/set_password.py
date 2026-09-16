#!/usr/bin/env python3
"""改密码 / 建账号。应用里没有注册和改密入口，改密码走这个脚本。

用法（在项目根目录）：
    python backend/scripts/set_password.py hemeng
    python backend/scripts/set_password.py hemeng --password 你的新密码

不带 --password 就交互式输入，不回显。账号不存在会新建。
服务器上在容器里执行：
    docker compose exec mygold python backend/scripts/set_password.py hemeng
"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal, ensure_schema  # noqa: E402
from app.users import claim_orphan_favorites, count_users, get_user, set_password  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="设置登录密码")
    parser.add_argument("username", help="账号")
    parser.add_argument("--password", default=None, help="新密码，省略则交互输入")
    args = parser.parse_args()

    password = args.password
    if not password:
        password = getpass.getpass("新密码：")
        if password != getpass.getpass("再输一次："):
            print("两次输入不一致")
            return 1

    ensure_schema()
    db = SessionLocal()
    try:
        existed = get_user(db, args.username) is not None
        set_password(db, args.username, password)
        print("%s 账号 %s，当前共 %d 个账号" % ("已更新" if existed else "已新建", args.username, count_users(db)))
        # 建的是第一个账号时，把加账号之前留下的收藏认领过来
        claimed = claim_orphan_favorites(db)
        if claimed:
            print("已把 %d 条旧收藏归到这个账号名下" % claimed)
    except ValueError as exc:
        print("失败：%s" % exc)
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
