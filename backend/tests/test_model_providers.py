import json
import unittest
from unittest.mock import patch

import httpx
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app import database
from backend.app.models import DeepSeekAccountConfig
from backend.app.stocks import ai_settings, deepseek, model_providers
import test_ai_settings as ai_settings_tests
from test_deepseek import SNAPSHOT, response


class ProviderTests(unittest.TestCase):
    setUp = ai_settings_tests.AISettingsTests.setUp

    def test_switch_requires_new_key_and_preserves_previous_on_error(self):
        with Session(self.engine) as db:
            ai_settings.save(db, 1, SecretStr("sk-deepseek-test"), "deepseek-flash")
            old = ai_settings.resolve(db, 1)
            with self.assertRaisesRegex(ValueError, "重新填写"):
                ai_settings.save(db, 1, None, "qwen-plus", provider="qwen")
            self.assertEqual(ai_settings.resolve(db, 1), old)
            ai_settings.save(db, 1, SecretStr("sk-qwen-test"), "qwen-plus", provider="qwen")
            new = ai_settings.resolve(db, 1)
            self.assertEqual(new.provider, "qwen")
            self.assertEqual(new.key.get_secret_value(), "sk-qwen-test")
            self.assertNotEqual(old.scope, new.scope)
            with self.assertRaises(ValueError):
                ai_settings.save(db, 1, None, "Qwen/model", provider="custom", base_url="https://gateway.example/v1")

    def test_no_foreign_provider_fallback_to_deepseek_env(self):
        with Session(self.engine) as db, patch.object(ai_settings.settings, "deepseek_api_key", SecretStr("deepseek-env-test")):
            ai_settings.save(db, 1, SecretStr("qwen-key-test"), "qwen-plus", provider="qwen")
            row = db.get(DeepSeekAccountConfig, 1)
            row.encrypted_key = None
            db.commit()
            self.assertFalse(ai_settings.resolve(db, 1).key.get_secret_value())

    def test_provider_payloads_and_exact_paths(self):
        from dataclasses import replace
        base = ai_settings.Credentials(SecretStr("provider-test-key"), "test-model", "scope", "account")
        for provider, spec in model_providers.PROVIDERS.items():
            if provider == "custom":
                continue
            model = "qwen-plus" if provider == "qwen" else "test-model"
            config = replace(base, provider=provider, base_url=spec["base_url"], token_field=spec["token_field"], model=model)
            def handler(request):
                self.assertEqual(str(request.url), spec["base_url"] + "/chat/completions")
                body = json.loads(request.content)
                self.assertEqual(body[spec["token_field"]], 4096)
                self.assertEqual("thinking" in body, provider == "deepseek")
                self.assertEqual("enable_thinking" in body, provider == "qwen")
                return httpx.Response(200, json=response())
            with self.subTest(provider=provider):
                self.assertTrue(deepseek.analyze(SNAPSHOT, httpx.MockTransport(handler), config)["items"])

    def test_prompt_only_json_compatibility(self):
        config = ai_settings.Credentials(SecretStr("test-compatible-key"), "test-model", "scope", "account", json_mode="prompt")
        def handler(request):
            self.assertNotIn("response_format", json.loads(request.content))
            return httpx.Response(200, json=response())
        self.assertTrue(deepseek.analyze(SNAPSHOT, httpx.MockTransport(handler), config)["items"])

    def test_rejects_unsafe_and_wrong_provider_urls(self):
        for url in ("http://api.example.com/v1", "https://localhost/v1", "https://127.0.0.1/v1",
                    "https://169.254.169.254", "https://internal.local/v1", "https://user:pass@api.example.com/v1",
                    "https://api.example.com/v1?key=secret", "https://api.example.com/v1#secret",
                    "https://api.example.com/v1/chat/completions"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                model_providers.normalize_base("custom", url)
        with self.assertRaises(ValueError):
            model_providers.normalize_base("openai", "https://other.example/v1")
        self.assertEqual(model_providers.normalize_base("qwen", "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/"),
                         "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")

    def test_custom_dns_validation_and_pinned_tls_host(self):
        config = ai_settings.Credentials(SecretStr("custom-endpoint-test"), "model", "scope", "account",
                                        provider="custom", base_url="https://gateway.example.com/v1")
        def handler(request):
            self.assertEqual(request.url.host, "93.184.216.34")
            self.assertEqual(request.headers["Host"], "gateway.example.com")
            self.assertEqual(request.extensions["sni_hostname"], "gateway.example.com")
            return httpx.Response(200, json=response())
        with patch.object(model_providers.socket, "getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 443))]):
            self.assertTrue(deepseek.analyze(SNAPSHOT, httpx.MockTransport(handler), config)["items"])
        for addresses in (["127.0.0.1"], ["93.184.216.34", "10.0.0.1"], ["::1"]):
            resolved = [(None, None, None, None, (address, 443)) for address in addresses]
            with patch.object(model_providers.socket, "getaddrinfo", return_value=resolved), self.assertRaises(ValueError):
                deepseek.analyze(SNAPSHOT, httpx.MockTransport(handler), config)

    def test_redirect_does_not_forward_key_to_another_host(self):
        calls = []
        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(302, headers={"Location": "https://other.example/"})
        config = ai_settings.Credentials(SecretStr("test-redirect-key"), "model", "scope", "account")
        with self.assertRaises(ValueError):
            deepseek.analyze(SNAPSHOT, httpx.MockTransport(handler), config)
        self.assertEqual(len(calls), 1)

    def test_model_list_absent_is_not_reported_as_invalid_key(self):
        config = ai_settings.Credentials(SecretStr("models-unsupported-key"), "model", "scope", "account")
        result = ai_settings.test_connection(config, 1, httpx.MockTransport(lambda request: httpx.Response(404)))
        self.assertFalse(result["ok"])
        self.assertIn("未提供模型列表", result["message"])

    def test_generation_probe_validates_same_analysis_format(self):
        config = ai_settings.Credentials(SecretStr("probe-test-key"), "model", "scope", "account")
        def handler(request):
            body = json.loads(request.content)
            self.assertEqual(json.loads(body["messages"][1]["content"])["items"][0]["name"], "格式测试样本")
            report = {"summary": "仅测试格式。", "items": [{"code": "000001", "view": "等待确认", "reason": "测试数据", "risk": "非真实行情", "trigger": "等待"}]}
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(report)}}]})
        self.assertTrue(ai_settings.test_generation(config, httpx.MockTransport(handler))["ok"])

    def test_legacy_schema_migration_preserves_encrypted_key(self):
        # 使用独立内存旧表，验证升级两次也不会重写既有密钥。
        from sqlalchemy import create_engine
        engine = create_engine("sqlite://")
        encrypted = ai_settings.cipher().encrypt(b"legacy-test-key").decode()
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE deepseek_account_configs (user_id INTEGER PRIMARY KEY, encrypted_key TEXT, model VARCHAR(64), enabled INTEGER, revision VARCHAR(36), updated_at DATETIME)"))
            connection.execute(text("INSERT INTO deepseek_account_configs VALUES (1, :key, 'deepseek-flash', 1, 'legacy', '2026-11-26 10:00:00')"), {"key": encrypted})
        with patch.object(database, "engine", engine):
            database.ensure_schema()
            database.ensure_schema()
        with Session(engine) as db:
            config = ai_settings.resolve(db, 1)
            self.assertEqual(config.provider, "deepseek")
            self.assertEqual(config.base_url, "https://api.deepseek.com")
            self.assertEqual(config.key.get_secret_value(), "legacy-test-key")
        engine.dispose()
