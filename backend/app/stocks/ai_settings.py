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
from sqlalchemy import select

from ..config import DATA_DIR, settings
from ..models import DeepSeekAccountConfig, StockAIProfile
from ..timeutil import now_local
from . import model_providers

KEY_FILE = DATA_DIR / "api_key_secret"
LEGACY_PROFILE_ID = "default"
_write_lock = threading.Lock()


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
    profile_id: str = LEGACY_PROFILE_ID
    name: str | None = None


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


def _default_model(provider):
    preset_model = model_providers.PROVIDERS[provider]["default_model"]
    return (settings.deepseek_model.strip() or preset_model) if provider == "deepseek" else preset_model


def _credentials(row, user_id, *, profile_id=LEGACY_PROFILE_ID, name=None):
    model = row.model if row else _default_model("deepseek")
    updated = row.updated_at.isoformat() if row else None
    scope = "account:%d:%s" % (user_id, row.revision if row else "server")
    extra = dict(provider=(row.provider or "deepseek") if row else "deepseek",
                 base_url=(row.base_url or "https://api.deepseek.com") if row else "https://api.deepseek.com",
                 json_mode=(row.json_mode or "json_object") if row else "json_object",
                 token_field=(row.token_field or "max_tokens") if row else "max_tokens",
                 profile_id=profile_id, name=name)
    if row and profile_id == LEGACY_PROFILE_ID and not row.enabled:
        return Credentials(SecretStr(""), model, scope, "disabled", updated, **extra)
    if row and row.encrypted_key:
        try:
            key = cipher().decrypt(row.encrypted_key.encode()).decode()
        except (InvalidToken, ValueError, OSError):
            return Credentials(SecretStr(""), model, scope, "account", updated,
                               "已保存的密钥无法解密，请重新填写并保存。", **extra)
        return Credentials(SecretStr(key), model, scope, "account", updated, **extra)
    key = settings.deepseek_api_key if profile_id == LEGACY_PROFILE_ID and extra["provider"] == "deepseek" else SecretStr("")
    return Credentials(key, model, scope, "server" if key.get_secret_value().strip() else "none", updated, **extra)


def resolve(db, user_id):
    return _credentials(db.get(DeepSeekAccountConfig, user_id), user_id)


def provider_presets():
    return [dict(value, id=key, default_model=_default_model(key)) for key, value in model_providers.PROVIDERS.items()]


def profile_status(credentials):
    label = model_providers.PROVIDERS[credentials.provider]["label"]
    return {"configured": bool(credentials.key.get_secret_value().strip()), "model": credentials.model,
            "source": credentials.source, "updated_at": credentials.updated_at, "error": credentials.error,
            "id": credentials.profile_id, "name": credentials.name or label, "provider_label": label,
            "provider": credentials.provider, "base_url": credentials.base_url,
            "json_mode": credentials.json_mode, "token_field": credentials.token_field}


def public_status(credentials):
    return {**profile_status(credentials), "providers": provider_presets()}


def _apply_config(row, current, api_key, model=None, provider=None, base_url=None, json_mode=None, token_field=None):
    # 空密钥表示保留现有配置，绝不把掩码当成密钥存储。
    key = api_key.get_secret_value().strip() if api_key is not None else ""
    if key and (len(key) < 8 or len(key) > 512 or any(char.isspace() or ord(char) < 32 for char in key)):
        raise ValueError("API Key 格式不正确，请粘贴完整密钥，勿包含空格或换行。")
    provider = provider or (current.provider if current else "deepseek")
    changed_provider = current is None or provider != current.provider
    base_url = model_providers.normalize_base(provider, base_url if base_url is not None else (None if changed_provider else current.base_url))
    if not key and current is not None and (changed_provider or base_url != current.base_url):
        raise ValueError("切换服务商或 API 地址时，请重新填写对应的 API Key。")
    preset = model_providers.PROVIDERS[provider]
    model = model if model is not None else (_default_model(provider) if changed_provider else current.model)
    if not model:
        raise ValueError("请填写此服务商支持的模型名称。")
    json_mode = json_mode or (preset["json_mode"] if changed_provider else current.json_mode)
    token_field = token_field or (preset["token_field"] if changed_provider else current.token_field)
    if json_mode not in {"json_object", "prompt"} or token_field not in {"max_tokens", "max_completion_tokens"}:
        raise ValueError("不支持该 JSON 或 Token 参数配置。")
    if not key and (current is None or not current.key.get_secret_value()):
        raise ValueError("请先填写 API Key。")
    if key:
        try:
            row.encrypted_key = cipher().encrypt(key.encode()).decode()
        except (OSError, ValueError):
            raise ValueError("服务器无法加密保存密钥，请检查数据目录权限。") from None
    fields = {"model": model, "provider": provider, "base_url": base_url, "json_mode": json_mode, "token_field": token_field}
    if current is None or key or current.source == "disabled" or any(getattr(current, k) != v for k, v in fields.items()):
        row.revision = str(uuid4())
    for field, value in fields.items():
        setattr(row, field, value)
    row.updated_at = now_local()


def save(db, user_id, api_key, model=None, provider=None, base_url=None, json_mode=None, token_field=None):
    with _write_lock:
        current = resolve(db, user_id)
        row = db.get(DeepSeekAccountConfig, user_id)
        if row is None:
            row = DeepSeekAccountConfig(user_id=user_id)
            db.add(row)
        _apply_config(row, current, api_key, model, provider, base_url, json_mode, token_field)
        if row.revision is None:
            row.revision = str(uuid4())
        row.enabled = 1
        db.commit()
    return public_status(resolve(db, user_id))


def disable(db, user_id):
    with _write_lock:
        row = db.get(DeepSeekAccountConfig, user_id)
        if row is None:
            row = DeepSeekAccountConfig(user_id=user_id, model=_default_model("deepseek"))
            db.add(row)
        row.encrypted_key = None
        row.enabled = 0
        row.revision = str(uuid4())
        row.updated_at = now_local()
        db.commit()
    return public_status(resolve(db, user_id))


def _profile_rows(db, user_id):
    return list(db.scalars(select(StockAIProfile).where(StockAIProfile.user_id == user_id)
                           .order_by(StockAIProfile.name, StockAIProfile.id)))


def profiles(db, user_id, legacy):
    available = [legacy] if legacy and legacy.source in ("account", "server") else []
    available.extend(_credentials(row, user_id, profile_id=row.id, name=row.name)
                     for row in _profile_rows(db, user_id))
    return available


def analysis_configs(db, user_id):
    legacy = resolve(db, user_id)
    return {"ai_config": legacy, "ai_profiles": profiles(db, user_id, legacy)}


def _owned_row(db, user_id, profile_id):
    row = db.get(StockAIProfile, profile_id)
    if row is None or row.user_id != user_id:
        raise LookupError("找不到这套 AI 配置。")
    return row


def get_profile(db, user_id, profile_id):
    if profile_id == LEGACY_PROFILE_ID:
        credentials = resolve(db, user_id)
        if credentials.source not in ("account", "server"):
            raise LookupError("找不到这套 AI 配置。")
        return credentials
    row = _owned_row(db, user_id, profile_id)
    return _credentials(row, user_id, profile_id=row.id, name=row.name)


def save_profile(db, user_id, payload, profile_id=None):
    values = payload.model_dump(exclude={"name"})
    if profile_id == LEGACY_PROFILE_ID:
        get_profile(db, user_id, profile_id)
        return save(db, user_id, **values)
    with _write_lock:
        if profile_id is None:
            row = StockAIProfile(id=uuid4().hex, user_id=user_id)
            current = None
        else:
            row = _owned_row(db, user_id, profile_id)
            current = _credentials(row, user_id, profile_id=row.id, name=row.name)
        _apply_config(row, current, **values)
        name = (payload.name or "").strip() if payload.name is not None else row.name
        if not name:
            label = model_providers.PROVIDERS[row.provider]["label"]
            labels = {item.name for item in _profile_rows(db, user_id) if item.id != row.id}
            legacy = resolve(db, user_id)
            if legacy.source in ("account", "server"):
                labels.add(model_providers.PROVIDERS[legacy.provider]["label"])
            name = label
            suffix = 2
            while name in labels:
                name = f"{label} {suffix}"
                suffix += 1
        row.name = name
        db.add(row)
        db.commit()
        return profile_status(_credentials(row, user_id, profile_id=row.id, name=row.name))


def delete_profile(db, user_id, profile_id):
    if profile_id == LEGACY_PROFILE_ID:
        get_profile(db, user_id, profile_id)
        disable(db, user_id)
        return
    with _write_lock:
        db.delete(_owned_row(db, user_id, profile_id))
        db.commit()


def select_profiles(available, requested):
    usable = {profile.profile_id: profile for profile in available if profile.key.get_secret_value().strip()}
    if requested is None:
        return list(usable.values())[:1]
    if not requested or len(set(requested)) != len(requested) or not set(requested) <= usable.keys():
        raise ValueError("请选择当前账号中有效且不重复的 AI 配置。")
    return [usable[key] for key in requested]


_test_lock = threading.Lock()
_test_times = {}


def test_connection(credentials, user_id, transport=None):
    if not credentials.key.get_secret_value():
        raise ValueError(credentials.error or "请先保存 API Key，再测试连接。")
    with _test_lock:
        scope = (user_id, credentials.profile_id)
        last = _test_times.get(scope)
        if last is not None and time.monotonic() - last < 10:
            raise ValueError("请间隔十秒再测试连接。")
        _test_times[scope] = time.monotonic()
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
