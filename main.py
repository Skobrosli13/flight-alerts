"""
Entry point for the Flight Deal Alerter.

Usage:
  python main.py               Start the live scheduler (runs forever)
  python main.py --seed        Bootstrap price history (run once before starting)
  python main.py --dry-run     One search job with mocked API/email (for testing)
  python main.py --monitor     Print status report and exit
  python main.py --test-email  Send a test deal email and exit
"""

import sys
import logging

import config
from utils import setup_logging
import database as db


def main() -> None:
    args = set(sys.argv[1:])

    setup_logging(level=config.LOG_LEVEL, log_file=config.LOG_FILE)
    log = logging.getLogger(__name__)

    db.init_database()

    # ------------------------------------------------------------------ #
    if "--monitor" in args:
        from monitor import print_report
        conn = db.get_connection()
        try:
            print_report(conn)
        finally:
            conn.close()
        return

    # ------------------------------------------------------------------ #
    if "--test-email" in args:
        from notifier import send_deal_alert
        test_deal = {
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
            "duration_minutes":  450,
            "observation_count": 24,
        }
        dry = "--dry-run" in args
        ok = send_deal_alert(test_deal, dry_run=dry)
        print("Email sent successfully." if ok else "Email failed — check logs.")
        return

    # ------------------------------------------------------------------ #
    if "--seed" in args:
        log.info("Running seed script to pre-populate price history...")
        import scripts.seed_history as seed
        seed.run()
        return

    # ------------------------------------------------------------------ #
    if "--dry-run" in args:
        log.info("Running a single dry-run job (no API calls, no emails sent)")
        from scheduler import search_job
        search_job(dry_run=True)
        return

    # ------------------------------------------------------------------ #
    # Normal operation: start the scheduler
    log.info("Starting Flight Deal Alerter for IAD / DCA / BWI")
    log.info(
        "Settings: threshold=%.0f%% | budget=%d credits/month | "
        "check every 6h | %d destinations",
        config.DEAL_THRESHOLD * 100,
        config.MONTHLY_BUDGET,
        len(__import__("destinations").SEARCH_PRIORITY),
    )
    from scheduler import start
    start()


if __name__ == "__main__":
    main()
