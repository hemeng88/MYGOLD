from datetime import datetime
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.auth import require_auth
from backend.app.database import Base, get_db
from backend.app.models import DeepSeekAccountConfig
from backend.app.routers.api import router
from backend.app.stocks import ai_settings, deepseek


class AISettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "secret"
        self.patches = [patch.object(ai_settings, "KEY_FILE", self.path),
                        patch.object(ai_settings.settings, "deepseek_api_key", SecretStr("")),
                        patch.object(ai_settings, "_test_times", {})]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)

    def test_encrypted_at_rest_and_public_status_never_returns_key(self):
        with Session(self.engine) as db:
            status = ai_settings.save(db, 1, SecretStr("sk-test-personal-123"), "deepseek-flash")
            stored = db.get(DeepSeekAccountConfig, 1)
            self.assertNotIn("sk-test-personal-123", stored.encrypted_key)
            self.assertNotIn("sk-test-personal-123", json.dumps(status))
            self.assertEqual(ai_settings.resolve(db, 1).key.get_secret_value(), "sk-test-personal-123")
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        # 新Session模拟重启后读取，密钥与持久化加密文件仍可解密。
        with Session(self.engine) as db:
            self.assertTrue(ai_settings.public_status(ai_settings.resolve(db, 1))["configured"])

    def test_account_isolation_keep_replace_and_disable(self):
        with Session(self.engine) as db:
            ai_settings.save(db, 1, SecretStr("sk-test-original"), "deepseek-flash")
            before = ai_settings.resolve(db, 1)
            self.assertFalse(ai_settings.resolve(db, 2).key.get_secret_value())
            ai_settings.save(db, 1, None, "deepseek-v4-pro")
            kept = ai_settings.resolve(db, 1)
            self.assertEqual(kept.key.get_secret_value(), before.key.get_secret_value())
            self.assertNotEqual(kept.scope, before.scope)
            self.assertEqual(kept.model, "deepseek-v4-pro")
            ai_settings.save(db, 1, SecretStr("sk-test-replacement"), "deepseek-flash")
            self.assertEqual(ai_settings.resolve(db, 1).key.get_secret_value(), "sk-test-replacement")
            ai_settings.save(db, 2, SecretStr("sk-second-user"), "deepseek-flash")
            result = ai_settings.disable(db, 1)
            self.assertFalse(result["configured"])
            self.assertIsNone(db.get(DeepSeekAccountConfig, 1).encrypted_key)
            self.assertTrue(ai_settings.resolve(db, 2).key.get_secret_value())

    def test_delete_disables_server_fallback_for_this_account_only(self):
        with Session(self.engine) as db, patch.object(ai_settings.settings, "deepseek_api_key", SecretStr("server-key-test")):
            self.assertEqual(ai_settings.resolve(db, 1).source, "server")
            ai_settings.disable(db, 1)
            self.assertEqual(ai_settings.resolve(db, 1).source, "disabled")
            self.assertFalse(ai_settings.resolve(db, 1).key.get_secret_value())
            self.assertTrue(ai_settings.resolve(db, 2).key.get_secret_value())

    def test_invalid_key_and_corrupt_ciphertext_are_handled(self):
        with Session(self.engine) as db:
            for key in (None, SecretStr("short"), SecretStr("internal space here")):
                with self.assertRaises(ValueError):
                    ai_settings.save(db, 1, key, "deepseek-flash")
                db.rollback()
            ai_settings.save(db, 1, SecretStr("sk-good-test-key"), "deepseek-flash")
            row = db.get(DeepSeekAccountConfig, 1)
            row.encrypted_key = "corrupted"
            db.commit()
            status = ai_settings.public_status(ai_settings.resolve(db, 1))
            self.assertFalse(status["configured"])
            self.assertIn("无法解密", status["error"])

    def test_connection_uses_models_endpoint_and_saved_key(self):
        config = ai_settings.Credentials(SecretStr("sk-private-test"), "deepseek-flash", "scope", "account")
        def handler(request):
            self.assertEqual(str(request.url), "https://api.deepseek.com/models")
            self.assertEqual(request.headers["Authorization"], "Bearer sk-private-test")
            return httpx.Response(200, json={"data": [{"id": "deepseek-flash"}]})
        result = ai_settings.test_connection(config, 1, httpx.MockTransport(handler))
        self.assertTrue(result["ok"])
        self.assertNotIn("sk-private-test", json.dumps(result))
        with self.assertRaisesRegex(ValueError, "十秒"):
            ai_settings.test_connection(config, 1, httpx.MockTransport(handler))

    def test_connection_errors_do_not_expose_response_body(self):
        config = ai_settings.Credentials(SecretStr("sk-private-test"), "deepseek-flash", "scope", "account")
        transport = httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "sk-private-test"}))
        with self.assertRaises(ValueError) as exc:
            ai_settings.test_connection(config, 1, transport)
        self.assertNotIn("sk-private-test", str(exc.exception))

    def test_private_credentials_are_used_and_scope_changes_on_replacement(self):
        from test_deepseek import SNAPSHOT, response
        with Session(self.engine) as db:
            ai_settings.save(db, 1, SecretStr("sk-first-user"), "deepseek-flash")
            first = ai_settings.resolve(db, 1)
            ai_settings.save(db, 2, SecretStr("sk-second-user"), "deepseek-v4-pro")
            second = ai_settings.resolve(db, 2)
            self.assertIsNot(deepseek._scope(SNAPSHOT, first), deepseek._scope(SNAPSHOT, second))
            old = deepseek._scope(SNAPSHOT, first)
            ai_settings.save(db, 1, SecretStr("sk-first-replaced"), "deepseek-flash")
            replaced = ai_settings.resolve(db, 1)
            self.assertIsNot(old, deepseek._scope(SNAPSHOT, replaced))
        def handler(request):
            self.assertEqual(request.headers["Authorization"], "Bearer sk-second-user")
            self.assertEqual(json.loads(request.content)["model"], "deepseek-v4-pro")
            return httpx.Response(200, json=response())
        self.assertTrue(deepseek.analyze(SNAPSHOT, httpx.MockTransport(handler), second)["items"])

    def test_api_requires_auth_and_allows_only_current_account(self):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        def session():
            with Session(self.engine) as db:
                yield db
        app.dependency_overrides[get_db] = session
        current_user = [1]
        with TestClient(app) as client:
            for method, path in (("get", "/api/settings/deepseek"), ("put", "/api/settings/deepseek"),
                                 ("delete", "/api/settings/deepseek"), ("post", "/api/settings/deepseek/test")):
                args = {"json": {"api_key": "sk-valid-test", "model": "deepseek-flash"}} if method == "put" else {}
                self.assertEqual(getattr(client, method)(path, **args).status_code, 401)
            app.dependency_overrides[require_auth] = lambda: SimpleNamespace(id=current_user[0])
            saved = client.put("/api/settings/deepseek", json={"api_key": "sk-private-user-one", "model": "deepseek-flash"})
            self.assertEqual(saved.status_code, 200)
            self.assertNotIn("sk-private-user-one", saved.text)
            current_user[0] = 2
            self.assertFalse(client.get("/api/settings/deepseek").json()["configured"])
            client.delete("/api/settings/deepseek")
            current_user[0] = 1
            self.assertTrue(client.get("/api/settings/deepseek").json()["configured"])
            self.assertNotIn("encrypted_key", client.get("/api/settings/deepseek").text)

    def test_api_presets_allow_saving_with_only_provider_and_key(self):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        def session():
            with Session(self.engine) as db:
                yield db
        app.dependency_overrides[get_db] = session
        app.dependency_overrides[require_auth] = lambda: SimpleNamespace(id=1)
        with TestClient(app) as client, patch.object(ai_settings.settings, "deepseek_model", "deepseek-v4-pro"):
            path = "/api/settings/ai"
            for provider, host in (("minimax", "api.minimax.cn"), ("minimax_global", "api.minimax.io")):
                with self.subTest(provider=provider):
                    key = "sk-test-" + provider
                    saved = client.put(path, json={"provider": provider, "api_key": key})
                    self.assertEqual(saved.status_code, 200)
                    self.assertNotIn(key, saved.text)
                    status = saved.json()
                    self.assertEqual((status["base_url"], status["model"], status["json_mode"], status["token_field"]),
                                     ("https://" + host + "/v1", "MiniMax-M3.1-Flash", "prompt", "max_completion_tokens"))
                    preset = next(row for row in status["providers"] if row["id"] == provider)
                    self.assertEqual(preset["json_mode"], "prompt")
            self.assertEqual(client.put(path, json={"provider": "deepseek"}).status_code, 400)
            saved = client.put(path, json={"provider": "deepseek", "api_key": "sk-test-deepseek"}).json()
            self.assertEqual((saved["base_url"], saved["model"], saved["json_mode"], saved["token_field"]),
                             ("https://api.deepseek.com", "deepseek-v4-pro", "json_object", "max_tokens"))


if __name__ == "__main__":
    unittest.main()
