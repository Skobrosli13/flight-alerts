"""
SerpApi (Google Flights) wrapper with rate limiting and budget tracking.

Schedule: every 46 minutes, 1 destination × 1 window per run.
42 total slots (21 dests × 2 windows) → ~31.3 credits/day → ~939 credits/month.
Full cycle: 42 × 46 min = 32.2 hours.
"""

import json
import logging
import time
import random
import sqlite3
from pathlib import Path
from typing import Optional

import config
import database as db
from utils import retry

log = logging.getLogger(__name__)

POLITE_DELAY = (1.5, 3.0) # seconds to sleep between API calls

BLOCKED_AIRLINES = {"Spirit Airlines", "Frontier Airlines"}

# Path to the fixture file used in dry-run / test mode
FIXTURE_PATH = Path(__file__).parent / "tests" / "fixtures" / "sample_serpapi_response.json"


# ---------------------------------------------------------------------------
# SerpApi call
# ---------------------------------------------------------------------------

def _load_fixture() -> dict:
    if FIXTURE_PATH.exists():
        with open(FIXTURE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    # Minimal stub so tests pass even without a captured fixture
    return {
        "best_flights": [
            {"price": 450, "flights": [{"airline": "Sample Airline"}], "layovers": []},
            {"price": 520, "flights": [{"airline": "Sample Airline"}], "layovers": [{"duration": 60}]},
        ],
        "other_flights": [],
    }


@retry(max_attempts=3, base_delay=10.0, jitter=5.0)
def _call_serpapi(params: dict) -> dict:
    from serpapi import GoogleSearch  # type: ignore
    result = GoogleSearch(params).get_dict()
    time.sleep(random.uniform(*POLITE_DELAY))
    return result


def execute_search(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str,
    dry_run: bool = False,
) -> Optional[dict]:
    """
    Execute a single round-trip search via SerpApi.
    Returns the raw response dict, or None on failure.
    In dry_run mode, returns fixture data without hitting the API.
    """
    if dry_run:
        log.debug("DRY RUN: %s→%s %s/%s", origin, destination, departure_date, return_date)
        return _load_fixture()

    params = {
        "engine":          "google_flights",
        "departure_id":    origin,
        "arrival_id":      destination,
        "outbound_date":   departure_date,
        "return_date":     return_date,
        "currency":        "USD",
        "hl":              "en",
        "gl":              "us",
        "type":            "1",        # 1 = round-trip
        "api_key":         config.SERPAPI_KEY,
    }

    log.debug("Searching %s→%s %s/%s", origin, destination, departure_date, return_date)
    result = _call_serpapi(params)
    return result


def _has_flights(response: dict) -> bool:
    return bool(response.get("best_flights") or response.get("other_flights"))


# ---------------------------------------------------------------------------
# Price extraction
# ---------------------------------------------------------------------------

def extract_prices(response: dict) -> list[dict]:
    """
    Parse SerpApi Google Flights response into a flat list of price records.
    Each record: {price, airline, stops, duration_minutes}
    Returns [] gracefully if response is malformed or has no results.
    """
    if not response:
        return []

    results = []
    all_flights = response.get("best_flights", []) + response.get("other_flights", [])

    for flight in all_flights:
        try:
            price = flight.get("price")
            if price is None:
                continue

            # Airline: first leg's airline name
            legs = flight.get("flights", [])
            airline = legs[0].get("airline", "Unknown") if legs else "Unknown"

            if airline in BLOCKED_AIRLINES:
                log.debug("Skipping blocked airline: %s", airline)
                continue

            # Stops = number of layovers
            stops = len(flight.get("layovers", []))

            if stops >= 2:
                log.debug("Skipping flight with %d layovers", stops)
                continue

            # Total duration in minutes (sum of all legs + layovers)
            duration = sum(
                leg.get("duration", 0) for leg in legs
            ) + sum(
                lay.get("duration", 0) for lay in flight.get("layovers", [])
            )

            results.append({
                "price":             float(price),
                "airline":           airline,
                "stops":             stops,
                "duration_minutes":  duration,
            })
        except (KeyError, TypeError, ValueError) as exc:
            log.debug("Skipping malformed flight entry: %s", exc)
            continue

    return results


# ---------------------------------------------------------------------------
# Budget check
# ---------------------------------------------------------------------------

def is_within_budget(conn: sqlite3.Connection) -> bool:
    used = db.get_monthly_search_count(conn)
    within = used < config.MONTHLY_BUDGET
    if not within:
        log.warning(
            "Monthly API budget ceiling reached (%d/%d). Skipping job run.",
            used, config.MONTHLY_BUDGET,
        )
    elif used >= config.MONTHLY_BUDGET * 0.80:
        log.warning(
            "API usage at %.0f%% of monthly budget (%d/%d searches).",
            100 * used / config.MONTHLY_BUDGET, used, config.MONTHLY_BUDGET,
        )
    return within
