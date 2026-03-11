"""
Unit tests for searcher.py — uses fixture data, no real API calls.

Run: pytest tests/test_searcher.py -v
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SERPAPI_KEY",       "test")
os.environ.setdefault("GMAIL_ADDRESS",     "test@example.com")
os.environ.setdefault("GMAIL_APP_PASSWORD","test")
os.environ.setdefault("ALERT_RECIPIENT",   "test@example.com")

import searcher


class TestExtractPrices:
    def test_extracts_prices_from_fixture(self):
        response = searcher._load_fixture()
        prices = searcher.extract_prices(response)
        assert len(prices) >= 1
        for p in prices:
            assert "price" in p
            assert "airline" in p
            assert "stops" in p
            assert isinstance(p["price"], float)

    def test_best_flights_cheaper_than_other(self):
        response = searcher._load_fixture()
        prices = searcher.extract_prices(response)
        min_price = min(p["price"] for p in prices)
        assert min_price == 387.0   # from fixture

    def test_nonstop_has_zero_stops(self):
        response = searcher._load_fixture()
        prices = searcher.extract_prices(response)
        nonstop = [p for p in prices if p["stops"] == 0]
        assert len(nonstop) >= 1

    def test_empty_response_returns_empty_list(self):
        assert searcher.extract_prices({}) == []
        assert searcher.extract_prices(None) == []

    def test_missing_best_flights_key(self):
        result = searcher.extract_prices({"other_flights": []})
        assert result == []

    def test_malformed_flight_entry_skipped(self):
        response = {
            "best_flights": [
                {"price": None, "flights": [], "layovers": []},       # no price
                {"price": 400, "flights": [{"airline": "AA"}], "layovers": []},  # valid
            ],
            "other_flights": [],
        }
        prices = searcher.extract_prices(response)
        assert len(prices) == 1
        assert prices[0]["price"] == 400.0


class TestDryRunSearch:
    def test_dry_run_returns_fixture_data(self):
        response = searcher.execute_search(
            "IAD", "CDG", "2026-06-13", "2026-06-23", dry_run=True
        )
        assert response is not None
        prices = searcher.extract_prices(response)
        assert len(prices) >= 1
