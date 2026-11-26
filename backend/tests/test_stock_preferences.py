from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.auth import require_auth
from backend.app.database import Base, get_db
from backend.app.routers.api import router
from backend.app.stocks import preferences, signals, deepseek


class BoardPreferenceTests(unittest.TestCase):
    def test_default_mainboard_persists_per_account(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            self.assertEqual(preferences.load_boards(db, 1), ["主板"])
            preferences.save_boards(db, 1, ["科创板", "主板", "主板"])
        with Session(engine) as db:
            self.assertEqual(preferences.load_boards(db, 1), ["主板", "科创板"])
            self.assertEqual(preferences.load_boards(db, 2), ["主板"])
            for boards in ([], ["港股"]):
                with self.assertRaises(ValueError):
                    preferences.save_boards(db, 2, boards)
        engine.dispose()

    def test_filter_happens_before_history_research(self):
        from test_stock_signals import quote
        rows = [quote(), quote("300001", "sz300001"), quote("688001", "sh688001"), quote("920001", "bj920001")]
        captured = []
        def builder(items, date):
            captured.extend(item["board"] for item in items)
            return items, {"strategies": []}, {}
        with patch.object(signals, "fetch_market_trade_date", return_value="2026-11-26"):
            result = signals.scan_market(get_json=lambda *args: rows, count_loader=lambda node: 4, research_builder=builder)
        self.assertEqual(captured, ["主板"])
        self.assertEqual(result["allowed_boards"], ["主板"])
        self.assertEqual(result["eligible"], 1)
        self.assertEqual(result["scanned"], 4)

    def test_scope_caches_and_ai_results_are_separate(self):
        with patch.object(signals, "_states", {}):
            default = signals._scope(["主板"])
            other = signals._scope(["主板", "创业板"])
            self.assertIsNot(default, other)
        with patch.object(deepseek, "_states", {}):
            self.assertIsNot(deepseek._scope({"allowed_boards": ["主板"]}),
                             deepseek._scope({"allowed_boards": ["创业板"]}))

    def test_preference_api_validates_and_uses_authenticated_user(self):
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[require_auth] = lambda: SimpleNamespace(id=7)
        app.dependency_overrides[get_db] = lambda: "test-db"
        with TestClient(app) as client, patch("backend.app.routers.api.save_boards", return_value=["主板"]) as save:
            response = client.put("/api/stocks/signals/preferences", json={"boards": ["主板"]})
            self.assertEqual(response.json(), {"boards": ["主板"]})
            save.assert_called_once_with("test-db", 7, ["主板"])
            self.assertEqual(client.put("/api/stocks/signals/preferences", json={"boards": []}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
