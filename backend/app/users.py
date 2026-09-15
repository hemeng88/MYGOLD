"""账号与密码校验。

密码用标准库的 PBKDF2-HMAC-SHA256 加盐哈希，不引入 bcrypt/passlib：
本项目依赖很少且全部 pin 死，PBKDF2 的强度对单账号自用场景够了。

存储格式是自描述的 `pbkdf2_sha256$<迭代数>$<盐 b64>$<哈希 b64>`，
以后想提高迭代数或换算法，老记录仍然能验证，不用一次性刷库。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User
from .timeutil import now_local

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 260_000
SALT_BYTES = 16


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "%s$%d$%s$%s" % (ALGORITHM, iterations, _b64(salt), _b64(digest))


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, raw_iterations, salt_b64, digest_b64 = (stored or "").split("$")
        if algorithm != ALGORITHM:
            return False
        iterations = int(raw_iterations)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, iterations)
    # 定长比较，避免按字节提前返回泄露信息
    return hmac.compare_digest(actual, expected)


def get_user(db: Session, username: str) -> Optional[User]:
    cleaned = (username or "").strip()
    if not cleaned:
        return None
    return db.scalar(select(User).where(User.username == cleaned))


def set_password(db: Session, username: str, password: str) -> User:
    """改密码，没有这个账号就新建。给命令行脚本用，接口层不暴露。"""
    if len(password or "") < 6:
        raise ValueError("密码至少 6 位")
    row = get_user(db, username)
    if row is None:
        row = User(username=(username or "").strip(), created_at=now_local())
        db.add(row)
    row.password_hash = hash_password(password)
    db.commit()
    db.refresh(row)
    return row


def count_users(db: Session) -> int:
    return len(db.scalars(select(User.id)).all())


def ensure_bootstrap_user(db: Session, username: str, password: str) -> Optional[User]:
    """库里一个账号都没有时，用 .env 里的初始密码建一个。

    只在空库时执行，所以之后改密码不会被启动时覆盖回去。
    没配密码就什么都不做 —— 代码里不留默认密码，那等于公开密码。
    """
    if not (password or "").strip():
        return None
    if count_users(db) > 0:
        return None
    return set_password(db, username, password)


def touch_login(db: Session, user: User) -> None:
    user.last_login_at = now_local()
    db.commit()
