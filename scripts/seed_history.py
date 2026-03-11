"""
One-time seed script to bootstrap price history before the live scheduler starts.

Searches each destination from each DC-area airport across multiple upcoming
date windows to quickly build up price observations for deal detection.

Usage: python main.py --seed
  OR:  python scripts/seed_history.py

NOTE: This will consume SerpApi credits. Estimated usage:
  3 origins × 26 destinations × 2 date windows = 156 searches
  This uses ~156 of your 1,000 monthly Starter plan credits in one shot.
  Run early in the month so the remaining ~844 credits cover live monitoring.
"""

import logging
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SERPAPI_KEY",       "")
os.environ.setdefault("GMAIL_ADDRESS",     "")
os.environ.setdefault("GMAIL_APP_PASSWORD","")
os.environ.setdefault("ALERT_RECIPIENT",   "")

import config
import database as db
import searcher
from destinations import SEARCH_PRIORITY
from utils import setup_logging, dates_for_window

log = logging.getLogger(__name__)


def run(dry_run: bool = False) -> None:
    setup_logging(config.LOG_LEVEL)
    db.init_database()
    conn = db.get_connection()

    total_searches = len(config.ORIGINS) * len(SEARCH_PRIORITY) * len(config.DATE_WINDOWS)
    log.info(
        "Seed run starting: %d origins × %d destinations × %d windows = %d searches",
        len(config.ORIGINS), len(SEARCH_PRIORITY), len(config.DATE_WINDOWS), total_searches,
    )

    completed = 0
    errors = 0

    for destination in SEARCH_PRIORITY:
        for window in config.DATE_WINDOWS:
            departure_date, return_date = dates_for_window(
                window["offset_weeks"], window["stay_nights"]
            )

            for origin in config.ORIGINS:
                response = searcher.execute_search(
                    origin=origin,
                    destination=destination,
                    departure_date=departure_date,
                    return_date=return_date,
                    dry_run=dry_run,
                )

                db.log_api_call(conn, origin, destination)

                if response:
                    prices = searcher.extract_prices(response)
                    for p in prices:
                        db.insert_price(
                            conn,
                            origin=origin,
                            destination=destination,
                            departure_date=departure_date,
                            return_date=return_date,
                            price_usd=p["price"],
                        )
                    completed += 1
                    log.info(
                        "[%d/%d] %s→%s %s: %d prices stored",
                        completed, total_searches, origin, destination,
                        departure_date, len(prices),
                    )
                else:
                    errors += 1
                    log.warning("No response for %s→%s %s", origin, destination, departure_date)

                conn.commit()
                time.sleep(1.0)  # polite pacing between calls

    log.info(
        "Seed complete: %d/%d searches succeeded, %d errors",
        completed, total_searches, errors,
    )
    conn.close()


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    run(dry_run=dry)
