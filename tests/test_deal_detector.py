"""
Unit tests for deal_detector.py using an in-memory SQLite database.
No API calls, no email — fully self-contained.

Run: pytest tests/test_deal_detector.py -v
"""

import sqlite3
import pytest
from datetime import datetime, timezone

# Patch config before importing modules that read it at import time
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SERPAPI_KEY",       "test")
os.environ.setdefault("GMAIL_ADDRESS",     "test@example.com")
os.environ.setdefault("GMAIL_APP_PASSWORD","test")
os.environ.setdefault("ALERT_RECIPIENT",   "test@example.com")

import config
# Override for tests
config.DEAL_THRESHOLD      = 0.40
config.MIN_OBSERVATIONS    = 10
config.ALERT_COOLDOWN_DAYS = 7
config.STATS_DATE_WINDOW   = 14
config.STATS_LOOKBACK_DAYS = 90

import database as db
import deal_detector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_in_memory_db() -> sqlite3.Connection:
    """Create an in-memory DB with the full schema."""
    original = config.DB_PATH
    config.DB_PATH = ":memory:"
    conn = db.get_connection()
    # Manually run init script on this connection
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS price_history (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            origin         TEXT NOT NULL,
            destination    TEXT NOT NULL,
            departure_date TEXT NOT NULL,
            return_date    TEXT NOT NULL,
            price_usd      REAL NOT NULL,
            cabin_class    TEXT NOT NULL DEFAULT 'economy',
            observed_at    TEXT NOT NULL,
            data_source    TEXT NOT NULL DEFAULT 'serpapi',
            UNIQUE(origin, destination, departure_date, return_date, observed_at)
        );
        CREATE TABLE IF NOT EXISTS sent_alerts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            origin          TEXT NOT NULL,
            destination     TEXT NOT NULL,
            departure_date  TEXT NOT NULL,
            return_date     TEXT NOT NULL,
            alerted_price   REAL NOT NULL,
            historical_avg  REAL NOT NULL,
            pct_below_avg   REAL NOT NULL,
            sent_at         TEXT NOT NULL,
            email_recipient TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scheduler_state (
            key        TEXT PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS api_usage (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            called_at    TEXT NOT NULL,
            origin       TEXT NOT NULL,
            destination  TEXT NOT NULL,
            credits_used INTEGER NOT NULL DEFAULT 1
        );
    """)
    config.DB_PATH = original
    return conn


def seed_prices(conn, origin, destination, departure_date, prices, return_date="2026-07-07"):
    """Insert a list of prices as historical observations."""
    for i, price in enumerate(prices):
        observed = f"2026-01-{i+1:02d}T12:00:00+00:00"
        conn.execute(
            """
            INSERT OR IGNORE INTO price_history
                (origin, destination, departure_date, return_date,
                 price_usd, observed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (origin, destination, departure_date, return_date, price, observed),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestColdStartGuard:
    def test_returns_none_when_insufficient_observations(self):
        conn = make_in_memory_db()
        # Only 5 observations — below MIN_OBSERVATIONS=10
        seed_prices(conn, "IAD", "CDG", "2026-06-13",
                    [600, 620, 580, 610, 590])

        prices = [{"price": 300.0, "airline": "Test", "stops": 0, "duration_minutes": 390}]
        result = deal_detector.evaluate_search_results(
            conn, "IAD", "CDG", "2026-06-13", "2026-06-23", prices, dry_run=True
        )
        assert result is None

    def test_activates_when_sufficient_observations(self):
        conn = make_in_memory_db()
        # 15 observations averaging ~$600 — a $300 price is 50% below
        seed_prices(conn, "IAD", "CDG", "2026-06-13",
                    [600, 620, 580, 610, 590, 605, 615, 595, 608, 612,
                     598, 603, 617, 585, 601])

        prices = [{"price": 300.0, "airline": "Test", "stops": 0, "duration_minutes": 390}]
        result = deal_detector.evaluate_search_results(
            conn, "IAD", "CDG", "2026-06-13", "2026-06-23", prices, dry_run=True
        )
        assert result is not None
        assert result["price"] == 300.0
        assert result["pct_below"] > 40.0


class TestDealDetection:
    def _make_conn_with_history(self):
        conn = make_in_memory_db()
        # 15 prices averaging ~$600
        seed_prices(conn, "IAD", "LHR", "2026-07-04",
                    [600, 620, 580, 610, 590, 605, 615, 595, 608, 612,
                     598, 603, 617, 585, 601])
        return conn

    def test_below_40pct_triggers_deal(self):
        conn = self._make_conn_with_history()
        prices = [{"price": 350.0, "airline": "BA", "stops": 0, "duration_minutes": 420}]
        result = deal_detector.evaluate_search_results(
            conn, "IAD", "LHR", "2026-07-04", "2026-07-14", prices, dry_run=True
        )
        assert result is not None
        assert result["origin"] == "IAD"
        assert result["destination"] == "LHR"
        assert result["pct_below"] >= 40.0

    def test_only_slightly_below_average_not_a_deal(self):
        conn = self._make_conn_with_history()
        # $560 is ~7% below avg — not a deal
        prices = [{"price": 560.0, "airline": "BA", "stops": 0, "duration_minutes": 420}]
        result = deal_detector.evaluate_search_results(
            conn, "IAD", "LHR", "2026-07-04", "2026-07-14", prices, dry_run=True
        )
        assert result is None

    def test_selects_cheapest_price(self):
        conn = self._make_conn_with_history()
        prices = [
            {"price": 500.0, "airline": "UA", "stops": 1, "duration_minutes": 600},
            {"price": 350.0, "airline": "BA", "stops": 0, "duration_minutes": 420},
            {"price": 420.0, "airline": "AA", "stops": 0, "duration_minutes": 440},
        ]
        result = deal_detector.evaluate_search_results(
            conn, "IAD", "LHR", "2026-07-04", "2026-07-14", prices, dry_run=True
        )
        assert result is not None
        assert result["price"] == 350.0
        assert result["airline"] == "BA"

    def test_empty_prices_returns_none(self):
        conn = self._make_conn_with_history()
        result = deal_detector.evaluate_search_results(
            conn, "IAD", "LHR", "2026-07-04", "2026-07-14", [], dry_run=True
        )
        assert result is None


class TestAlertCooldown:
    def test_no_duplicate_alert_within_cooldown(self):
        conn = make_in_memory_db()
        seed_prices(conn, "IAD", "NRT", "2026-08-01",
                    [900, 920, 880, 910, 890, 905, 915, 895, 908, 912,
                     898, 903, 917, 885, 901])

        # Record a recent alert for same route+date
        db.record_alert(
            conn, "IAD", "NRT", "2026-08-01", "2026-08-15",
            550.0, 900.0, 39.0, "test@example.com"
        )
        conn.commit()

        prices = [{"price": 520.0, "airline": "NH", "stops": 0, "duration_minutes": 840}]
        result = deal_detector.evaluate_search_results(
            conn, "IAD", "NRT", "2026-08-01", "2026-08-15", prices, dry_run=True
        )
        assert result is None   # cooldown blocks the alert


class TestDealInfoStructure:
    def test_deal_info_has_required_keys(self):
        conn = make_in_memory_db()
        seed_prices(conn, "BWI", "CUN", "2026-05-01",
                    [400, 420, 380, 410, 390, 405, 415, 395, 408, 412,
                     398, 403, 417, 385, 401])

        prices = [{"price": 200.0, "airline": "WN", "stops": 0, "duration_minutes": 210}]
        result = deal_detector.evaluate_search_results(
            conn, "BWI", "CUN", "2026-05-01", "2026-05-08", prices, dry_run=True
        )
        assert result is not None
        required_keys = [
            "origin", "destination", "origin_city", "dest_city",
            "departure_date", "return_date", "price", "historical_avg",
            "historical_min", "pct_below", "savings", "airline",
            "stops", "duration_minutes", "observation_count",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"
