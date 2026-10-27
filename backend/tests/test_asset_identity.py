import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app import database
from backend.app.funds import sources, favorites
from backend.app.models import FundFavorite
from backend.app.timeutil import now_local


class AssetIdentityTests(unittest.TestCase):
    def test_old_stock_identifier_migrates_without_losing_position(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(FundFavorite(user_id=1, code="000823", name="超声电子", asset_type="stock",
                                secid="0.000823", market="0", shares=100, cost_price=12, added_at=now_local()))
            db.commit()
        with patch.object(database, "engine", engine):
            database.ensure_schema()
            database.ensure_schema()
        with Session(engine) as db:
            row = favorites.get_favorite(db, 1, "0.000823")
            self.assertEqual((row.shares, row.cost_price), (100, 12))
        engine.dispose()

    def test_exact_stock_search_filters_other_markets_and_duplicates(self):
        rows = [
            {"Code": "000823", "Name": "同号基金", "QuoteID": "0.000823", "Classify": "Fund"},
            {"Code": "000823", "Name": "其它市场", "QuoteID": "116.000823"},
            {"Code": "000823", "Name": "超声电子", "QuoteID": "0.000823", "Classify": "AStock"},
            {"Code": "000823", "Name": "超声电子", "QuoteID": "0.000823", "Classify": "AStock"},
            {"Code": "000824", "Name": "其它股票", "QuoteID": "0.000824", "Classify": "AStock"},
        ]
        response = MagicMock()
        response.json.return_value = {"QuotationCodeTable": {"Data": rows}}
        with patch.object(sources.httpx, "Client") as client:
            client.return_value.__enter__.return_value.get.return_value = response
            results = sources.search_stocks("000823")
        self.assertEqual([(r["code"], r["name"]) for r in results], [("0.000823", "超声电子")])

    def test_same_number_fund_and_stock_have_independent_favorites(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        fund = {"code": "000823", "name": "同号基金", "asset_type": "fund"}
        stock = {"code": "0.000823", "name": "超声电子", "asset_type": "stock", "secid": "0.000823", "market": "0"}
        with Session(engine) as db, patch.object(favorites, "search_funds", return_value=[fund]), patch.object(favorites, "search_stocks", return_value=[stock]):
            a = favorites.add_favorite(db, 1, "000823")
            b = favorites.add_favorite(db, 1, "0.000823")
            self.assertNotEqual(a.id, b.id)
            self.assertEqual(b.name, "超声电子")
            self.assertEqual(favorites.add_favorite(db, 1, "0.000823").id, b.id)
            favorites.set_position(db, 1, b.code, 100, 12)
            self.assertIsNone(a.shares)
            self.assertEqual(b.shares, 100)
            self.assertEqual(len(favorites.list_favorites(db, 1)), 2)
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
