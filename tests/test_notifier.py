"""
Unit tests for notifier.py — no actual email sent, no SMTP connections.

Run: pytest tests/test_notifier.py -v
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SERPAPI_KEY",       "test")
os.environ.setdefault("GMAIL_ADDRESS",     "test@example.com")
os.environ.setdefault("GMAIL_APP_PASSWORD","test")
os.environ.setdefault("ALERT_RECIPIENT",   "test@example.com")

import notifier

SAMPLE_DEAL = {
    "origin":            "IAD",
    "destination":       "CDG",
    "origin_city":       "Washington Dulles",
    "dest_city":         "Paris (CDG)",
    "departure_date":    "2026-06-13",
    "return_date":       "2026-06-23",
    "price":             387.0,
    "historical_avg":    676.0,
    "historical_min":    412.0,
    "pct_below":         42.7,
    "savings":           289.0,
    "airline":           "Air France",
    "stops":             0,
    "duration_minutes":  390,
    "observation_count": 24,
}


class TestHTMLRendering:
    def test_html_contains_price(self):
        html = notifier.render_deal_html(SAMPLE_DEAL)
        assert "$387" in html

    def test_html_contains_route(self):
        html = notifier.render_deal_html(SAMPLE_DEAL)
        assert "IAD" in html
        assert "CDG" in html

    def test_html_contains_pct_below(self):
        html = notifier.render_deal_html(SAMPLE_DEAL)
        assert "42%" in html or "43%" in html

    def test_html_contains_google_flights_link(self):
        html = notifier.render_deal_html(SAMPLE_DEAL)
        assert "google.com/travel/flights" in html

    def test_html_contains_airline(self):
        html = notifier.render_deal_html(SAMPLE_DEAL)
        assert "Air France" in html

    def test_html_contains_nonstop(self):
        html = notifier.render_deal_html(SAMPLE_DEAL)
        assert "Nonstop" in html


class TestTextRendering:
    def test_text_contains_price(self):
        text = notifier.render_deal_text(SAMPLE_DEAL)
        assert "$387" in text

    def test_text_contains_route(self):
        text = notifier.render_deal_text(SAMPLE_DEAL)
        assert "IAD" in text
        assert "CDG" in text


class TestDryRun:
    def test_dry_run_returns_true(self, capsys):
        result = notifier.send_deal_alert(SAMPLE_DEAL, dry_run=True)
        assert result is True

    def test_dry_run_prints_to_stdout(self, capsys):
        notifier.send_deal_alert(SAMPLE_DEAL, dry_run=True)
        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out
        assert "IAD" in captured.out


class TestGoogleFlightsURL:
    def test_url_contains_airports(self):
        url = notifier.build_google_flights_url("IAD", "CDG", "2026-06-13", "2026-06-23")
        assert "IAD" in url
        assert "CDG" in url
        assert "google.com" in url

    def test_url_is_string(self):
        url = notifier.build_google_flights_url("BWI", "LHR", "2026-07-01", "2026-07-10")
        assert isinstance(url, str)
        assert url.startswith("https://")
