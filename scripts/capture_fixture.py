"""
Capture a real SerpApi response and save it as the test fixture.
Costs exactly 1 API credit.

Usage: python scripts/capture_fixture.py
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("GMAIL_ADDRESS",     "test@example.com")
os.environ.setdefault("GMAIL_APP_PASSWORD","test")
os.environ.setdefault("ALERT_RECIPIENT",   "test@example.com")

import config
from utils import dates_for_window

FIXTURE_PATH = Path(__file__).parent.parent / "tests" / "fixtures" / "sample_serpapi_response.json"


def main():
    from serpapi import GoogleSearch  # type: ignore

    departure_date, return_date = dates_for_window(offset_weeks=6, stay_nights=7)

    params = {
        "engine":        "google_flights",
        "departure_id":  "IAD",
        "arrival_id":    "LHR",
        "outbound_date": departure_date,
        "return_date":   return_date,
        "currency":      "USD",
        "hl":            "en",
        "gl":            "us",
        "type":          "1",
        "api_key":       config.SERPAPI_KEY,
    }

    print(f"Searching IAD→LHR {departure_date}/{return_date}...")
    result = GoogleSearch(params).get_dict()

    FIXTURE_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Fixture saved to {FIXTURE_PATH}")

    # Quick sanity check
    flights = result.get("best_flights", []) + result.get("other_flights", [])
    print(f"Found {len(flights)} flight options")
    for f in flights[:3]:
        print(f"  ${f.get('price')} — {f.get('flights', [{}])[0].get('airline', '?')}")


if __name__ == "__main__":
    main()
