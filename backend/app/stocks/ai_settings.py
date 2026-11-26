"""账号级模型服务配置；API 密钥加密落库，对客户端只返回状态。"""
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
from . import model_providers

KEY_FILE = DATA_DIR / "api_key_secret"


@dataclass(frozen=True)
class Credentials:
    key: SecretStr
    model: str
    scope: str
    source: str
    updated_at: str | None = None
    error: str | None = None
    provider: str = "deepseek"
    base_url: str = "https://api.deepseek.com"
    json_mode: str = "json_object"
    token_field: str = "max_tokens"


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
    extra = dict(provider=(row.provider or "deepseek") if row else "deepseek",
                 base_url=(row.base_url or "https://api.deepseek.com") if row else "https://api.deepseek.com",
                 json_mode=(row.json_mode or "json_object") if row else "json_object",
                 token_field=(row.token_field or "max_tokens") if row else "max_tokens")
    if row and not row.enabled:
        return Credentials(SecretStr(""), model, scope, "disabled", updated, **extra)
    if row and row.encrypted_key:
        try:
            key = cipher().decrypt(row.encrypted_key.encode()).decode()
        except (InvalidToken, ValueError, OSError):
            return Credentials(SecretStr(""), model, scope, "account", updated,
                               "已保存的密钥无法解密，请重新填写并保存。", **extra)
        return Credentials(SecretStr(key), model, scope, "account", updated, **extra)
    key = settings.deepseek_api_key if extra["provider"] == "deepseek" else SecretStr("")
    return Credentials(key, model, scope, "server" if key.get_secret_value().strip() else "none", updated, **extra)


def public_status(credentials):
    return {"configured": bool(credentials.key.get_secret_value().strip()), "model": credentials.model,
            "source": credentials.source, "updated_at": credentials.updated_at, "error": credentials.error,
            "provider": credentials.provider, "base_url": credentials.base_url,
            "json_mode": credentials.json_mode, "token_field": credentials.token_field,
            "providers": [dict(id=key, **value) for key, value in model_providers.PROVIDERS.items()]}


def save(db, user_id, api_key, model, provider=None, base_url=None, json_mode=None, token_field=None):
    # 空密钥表示保留现有配置，绝不把掩码当成密钥存储。
    key = api_key.get_secret_value().strip() if api_key is not None else ""
    if key and (len(key) < 8 or len(key) > 512 or any(char.isspace() or ord(char) < 32 for char in key)):
        raise ValueError("API Key 格式不正确，请粘贴完整密钥，勿包含空格或换行。")
    current = resolve(db, user_id)
    provider = provider or current.provider
    changed_provider = provider != current.provider
    base_url = model_providers.normalize_base(provider, base_url if base_url is not None else (None if changed_provider else current.base_url))
    if not key and (changed_provider or base_url != current.base_url):
        raise ValueError("切换服务商或 API 地址时，请重新填写对应的 API Key。")
    json_mode = json_mode or ("json_object" if changed_provider else current.json_mode)
    token_field = token_field or (model_providers.PROVIDERS[provider]["token_field"] if changed_provider else current.token_field)
    if json_mode not in {"json_object", "prompt"} or token_field not in {"max_tokens", "max_completion_tokens"}:
        raise ValueError("不支持该 JSON 或 Token 参数配置。")
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
    row.provider = provider
    row.base_url = base_url
    row.json_mode = json_mode
    row.token_field = token_field
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
        response = model_providers.request(credentials, "GET", "/models", transport=transport, timeout=10)
        models = {row["id"] for row in response.json()["data"]}
        if credentials.model not in models:
            return {"ok": False, "message": "密钥鉴权成功，但该账号的模型列表中没有所选模型，请检查模型名称。"}
        return {"ok": True, "message": "密钥鉴权成功，所选模型可用。余额及实际分析是否成功仍以分析请求为准。"}
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in (404, 405, 501):
            return {"ok": False, "message": "该服务未提供模型列表，不能据此判断 Key 无效。可点击“验证分析格式”检查兼容性（会产生少量费用）。"}
        if status in (401, 403):
            message = "模型服务鉴权失败，请检查 API Key 和账号权限。"
        elif status == 429:
            message = "模型服务请求受限，请稍后重试。"
        else:
            message = "模型服务暂不可用（HTTP %d）。" % status
        raise ValueError(message) from None
    except httpx.RequestError:
        raise ValueError("连接模型服务失败或超时，请稍后重试。") from None
    except model_providers.EndpointError:
        raise
    except (ValueError, TypeError, KeyError):
        raise ValueError("模型列表格式异常，请稍后重试。") from None


def test_generation(credentials, transport=None):
    from .deepseek import analyze
    if not credentials.key.get_secret_value():
        raise ValueError("请先保存 API Key。")
    # 使用固定测试行情，不上传账号持仓，也不启动全市场扫描。
    snapshot = {"fetched_at": now_local().isoformat(), "trade_date": now_local().date().isoformat(),
                "allowed_boards": ["主板"], "items": [{"code": "000001", "name": "格式测试样本",
                "price": 10, "watch_low": 9.9, "watch_high": 10, "breakout_price": 10.2,
                "invalidation_price": 9.5, "priority_eligible": False}]}
    analyze(snapshot, transport=transport, credentials=credentials)
    return {"ok": True, "message": "结构化分析格式验证通过；使用的是固定测试数据，本次调用会按服务商规则计费。"}
