"""账号级 DeepSeek 配置；API 密钥加密落库，对客户端只返回状态。"""
from __future__ import annotations

from dataclasses import dataclass
import os
import threading
import time
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
import httpx
from pydantic import SecretStr

from ..config import DATA_DIR, settings
from ..models import DeepSeekAccountConfig
from ..timeutil import now_local

KEY_FILE = DATA_DIR / "api_key_secret"


@dataclass(frozen=True)
class Credentials:
    key: SecretStr
    model: str
    scope: str
    source: str
    updated_at: str | None = None
    error: str | None = None


def cipher():
    try:
        value = KEY_FILE.read_bytes().strip()
    except FileNotFoundError:
        value = Fernet.generate_key()
        try:
            fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            value = KEY_FILE.read_bytes().strip()
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(value)
    return Fernet(value)


def resolve(db, user_id):
    row = db.get(DeepSeekAccountConfig, user_id)
    model = row.model if row else settings.deepseek_model
    updated = row.updated_at.isoformat() if row else None
    scope = "account:%d:%s" % (user_id, row.revision if row else "server")
    if row and not row.enabled:
        return Credentials(SecretStr(""), model, scope, "disabled", updated)
    if row and row.encrypted_key:
        try:
            key = cipher().decrypt(row.encrypted_key.encode()).decode()
        except (InvalidToken, ValueError, OSError):
            return Credentials(SecretStr(""), model, scope, "account", updated,
                               "已保存的密钥无法解密，请重新填写并保存。")
        return Credentials(SecretStr(key), model, scope, "account", updated)
    key = settings.deepseek_api_key
    return Credentials(key, model, scope, "server" if key.get_secret_value().strip() else "none", updated)


def public_status(credentials):
    return {"configured": bool(credentials.key.get_secret_value().strip()), "model": credentials.model,
            "source": credentials.source, "updated_at": credentials.updated_at, "error": credentials.error}


def save(db, user_id, api_key, model):
    # 空密钥表示保留现有配置，绝不把掩码当成密钥存储。
    key = api_key.get_secret_value().strip() if api_key is not None else ""
    if key and (len(key) < 8 or len(key) > 512 or any(char.isspace() or ord(char) < 32 for char in key)):
        raise ValueError("API Key 格式不正确，请粘贴完整密钥，勿包含空格或换行。")
    current = resolve(db, user_id)
    if not key and not current.key.get_secret_value():
        raise ValueError("请先填写 API Key。")
    row = db.get(DeepSeekAccountConfig, user_id)
    if row is None:
        row = DeepSeekAccountConfig(user_id=user_id)
        db.add(row)
    if key:
        try:
            row.encrypted_key = cipher().encrypt(key.encode()).decode()
        except (OSError, ValueError):
            raise ValueError("服务器无法加密保存密钥，请检查数据目录权限。") from None
    row.model = model
    row.enabled = 1
    row.revision = str(uuid4())
    row.updated_at = now_local()
    db.commit()
    return public_status(resolve(db, user_id))


def disable(db, user_id):
    row = db.get(DeepSeekAccountConfig, user_id)
    if row is None:
        row = DeepSeekAccountConfig(user_id=user_id, model=settings.deepseek_model)
        db.add(row)
    row.encrypted_key = None
    row.enabled = 0
    row.revision = str(uuid4())
    row.updated_at = now_local()
    db.commit()
    return public_status(resolve(db, user_id))


_test_lock = threading.Lock()
_test_times = {}


def test_connection(credentials, user_id, transport=None):
    if not credentials.key.get_secret_value():
        raise ValueError(credentials.error or "请先保存 API Key，再测试连接。")
    with _test_lock:
        last = _test_times.get(user_id)
        if last is not None and time.monotonic() - last < 10:
            raise ValueError("请间隔十秒再测试连接。")
        _test_times[user_id] = time.monotonic()
    try:
        with httpx.Client(timeout=10, transport=transport) as client:
            response = client.get("https://api.deepseek.com/models", headers={
                "Authorization": "Bearer " + credentials.key.get_secret_value(),
            })
            response.raise_for_status()
        models = {row["id"] for row in response.json()["data"]}
        if credentials.model not in models:
            return {"ok": False, "message": "密钥鉴权成功，但该账号的模型列表中没有所选模型，请检查模型名称。"}
        return {"ok": True, "message": "密钥鉴权成功，所选模型可用。余额及实际分析是否成功仍以分析请求为准。"}
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (401, 403):
            message = "DeepSeek 鉴权失败，请检查 API Key 和账号权限。"
        elif status == 429:
            message = "DeepSeek 请求受限，请稍后重试。"
        else:
            message = "DeepSeek 服务暂不可用（HTTP %d）。" % status
        raise ValueError(message) from None
    except httpx.RequestError:
        raise ValueError("连接 DeepSeek 失败或超时，请稍后重试。") from None
    except (ValueError, TypeError, KeyError):
        raise ValueError("DeepSeek 模型列表格式异常，请稍后重试。") from None
