"""
Deal detection logic.

Algorithm:
  1. Always write all current prices to price_history.
  2. Query historical stats for this route (mean, std, count).
  3. Cold-start guard: skip deal evaluation if count < MIN_OBSERVATIONS.
  4. A "deal" requires BOTH:
       a. current_price <= mean * (1 - DEAL_THRESHOLD)       [percentage check]
       b. current_price <  mean - 1.5 * std                  [z-score sanity check]
  5. Duplicate-alert guard: skip if same route+date was alerted within COOLDOWN_DAYS.
  6. Returns a deal_info dict (or None) for the notifier to act on.
"""

import logging
import sqlite3
from datetime import datetime
from typing import Optional

import config
import database as db
from destinations import get_destination_name, DOMESTIC_DESTINATIONS

EAST_COAST_DESTINATIONS = {"MIA", "MCO", "JFK", "BOS"}
WEEKEND_DEPART_DAYS = {3, 4}   # Thursday=3, Friday=4
WEEKEND_RETURN_DAYS = {6, 0}   # Sunday=6, Monday=0

log = logging.getLogger(__name__)


def evaluate_search_results(
    conn: sqlite3.Connection,
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str,
    prices: list[dict],
    dry_run: bool = False,
) -> Optional[dict]:
    """
    Write prices to DB, then check if the best current price is a deal.

    Returns a deal_info dict if a deal was found and not recently alerted,
    otherwise returns None.
    """
    if not prices:
        log.debug("No prices returned for %s→%s %s", origin, destination, departure_date)
        return None

    # --- Step 1: persist all observed prices ---
    for p in prices:
        db.insert_price(
            conn,
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date,
            price_usd=p["price"],
        )
    if not dry_run:
        conn.commit()

    # --- Step 2: get historical stats ---
    stats = db.get_price_stats(
        conn,
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        date_window_days=config.STATS_DATE_WINDOW,
        lookback_days=config.STATS_LOOKBACK_DAYS,
    )

    # --- Step 3: cold-start guard ---
    if stats is None or stats["count"] < config.MIN_OBSERVATIONS:
        log.debug(
            "%s→%s %s: only %d observations (need %d) — skipping deal check",
            origin, destination, departure_date,
            stats["count"] if stats else 0,
            config.MIN_OBSERVATIONS,
        )
        return None

    # --- Step 3b: east coast weekend-only guard ---
    if destination in EAST_COAST_DESTINATIONS:
        depart_dow = datetime.fromisoformat(departure_date).weekday()
        return_dow = datetime.fromisoformat(return_date).weekday()
        if depart_dow not in WEEKEND_DEPART_DAYS or return_dow not in WEEKEND_RETURN_DAYS:
            log.debug(
                "%s→%s %s: non-weekend dates (depart dow=%d, return dow=%d) — skipping east coast deal check",
                origin, destination, departure_date, depart_dow, return_dow,
            )
            return None

    # --- Step 4: find the best price ---
    # Domestic routes: nonstop only. International: nonstop preferred, 1-stop allowed.
    if destination in DOMESTIC_DESTINATIONS:
        candidate_prices = [p for p in prices if p["stops"] == 0]
        if not candidate_prices:
            log.debug("%s→%s %s: no nonstop flights — skipping domestic deal check",
                      origin, destination, departure_date)
            return None
    else:
        candidate_prices = prices

    best = min(candidate_prices, key=lambda p: (p["price"], p["stops"]))
    current_price = best["price"]
    mean = stats["mean"]
    std = stats["std"]

    pct_below = (mean - current_price) / mean
    threshold_price = mean * (1.0 - config.DEAL_THRESHOLD)
    zscore_price = mean - 1.5 * std

    is_deal = (current_price <= threshold_price) and (current_price < zscore_price or std == 0)

    log.debug(
        "%s→%s %s: $%.0f vs avg $%.0f (%.0f%% below) | deal=%s",
        origin, destination, departure_date,
        current_price, mean, pct_below * 100, is_deal,
    )

    if not is_deal:
        return None

    # --- Step 5: duplicate-alert guard ---
    if db.was_recently_alerted(
        conn, origin, destination, departure_date, config.ALERT_COOLDOWN_DAYS
    ):
        log.info(
            "DEAL found but recently alerted: %s→%s %s $%.0f",
            origin, destination, departure_date, current_price,
        )
        return None

    # --- Step 6: build deal_info ---
    savings = mean - current_price
    deal_info = {
        "origin":             origin,
        "destination":        destination,
        "origin_city":        get_destination_name(origin),
        "dest_city":          get_destination_name(destination),
        "departure_date":     departure_date,
        "return_date":        return_date,
        "price":              current_price,
        "historical_avg":     mean,
        "historical_min":     stats["min"],
        "pct_below":          round(pct_below * 100, 1),
        "savings":            round(savings, 0),
        "airline":            best["airline"],
        "stops":              best["stops"],
        "duration_minutes":   best.get("duration_minutes", 0),
        "observation_count":  stats["count"],
    }

    log.info(
        "DEAL FOUND: %s→%s %s $%.0f (%.0f%% below avg $%.0f)",
        origin, destination, departure_date,
        current_price, pct_below * 100, mean,
    )

    return deal_info
