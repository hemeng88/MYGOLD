"""登录与令牌。

账号密码存在数据库的 users 表里（见 users.py），这里只负责：
签发 HMAC 令牌、验签、以及把「需要登录」做成一个 FastAPI 依赖。

服务端不存会话，令牌自带签名和有效期，重启不用清理什么。
密钥 auth_secret 默认不写在代码里，而是进程启动时随机生成 ——
仓库是公开的，密钥一旦提交，任何人都能伪造令牌。代价是后端重启后要重新登录。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .users import get_user, touch_login, verify_password

_SECRET = (settings.auth_secret or secrets.token_urlsafe(32)).encode("utf-8")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: bytes) -> str:
    return _b64(hmac.new(_SECRET, payload, hashlib.sha256).digest())


def issue_token(username: str) -> str:
    payload = json.dumps(
        {"u": username, "exp": int(time.time()) + settings.auth_token_days * 86400},
        separators=(",", ":"),
    ).encode("utf-8")
    return "%s.%s" % (_b64(payload), _sign(payload))


def verify_token(token: str) -> Optional[str]:
    """验签并检查有效期，通过返回用户名，否则 None。"""
    if not token or "." not in token:
        return None
    body, _, signature = token.rpartition(".")
    try:
        payload = _unb64(body)
    except Exception:
        return None
    if not hmac.compare_digest(_sign(payload), signature):
        return None
    try:
        data = json.loads(payload)
    except Exception:
        return None
    if int(data.get("exp") or 0) < int(time.time()):
        return None
    return data.get("u") or None


def login(db: Session, username: str, password: str) -> tuple[str, str]:
    """账号密码对上就签发令牌，返回 (令牌, 用户名)；对不上抛 ValueError。"""
    user = get_user(db, username)
    # 账号不存在时也要走一次哈希校验，让耗时和密码错的情况接近，
    # 否则响应快慢能被用来判断账号是否存在
    stored = user.password_hash if user else _DUMMY_HASH
    ok = verify_password(password or "", stored)
    if not user or not ok:
        raise ValueError("账号或密码不对")
    touch_login(db, user)
    return issue_token(user.username), user.username


def require_auth(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> str:
    """挂在需要登录的路由上。前端在 Authorization 头里带 Bearer 令牌。"""
    prefix = "bearer "
    token = authorization[len(prefix) :] if authorization[: len(prefix)].lower() == prefix else ""
    username = verify_token(token.strip())
    if not username:
        raise HTTPException(status_code=401, detail="需要登录")
    # 令牌签名有效不代表账号还在：账号被删或改名后，旧令牌应立即失效
    if get_user(db, username) is None:
        raise HTTPException(status_code=401, detail="账号不存在，请重新登录")
    return username


# 账号不存在时拿来充数的哈希，密码是一串随机值，永远不会被猜中
_DUMMY_HASH = "pbkdf2_sha256$1$%s$%s" % (
    base64.b64encode(b"0" * 16).decode(),
    base64.b64encode(b"0" * 32).decode(),
)
