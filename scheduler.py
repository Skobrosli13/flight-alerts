"""
APScheduler setup and the main search_job function.

Uses BlockingScheduler (runs as a long-lived daemon process).
Job state is persisted in flights.db via SQLAlchemyJobStore so restarts
resume correctly.

Schedule: every 46 minutes, 1 destination × 1 window per run.
  42 total slots (21 dests × 2 windows) rotate continuously via sweep_cursor.
  Slots 0–20:  near-term window for each destination in SEARCH_PRIORITY order
  Slots 21–41: far-out window for each destination in SEARCH_PRIORITY order
  Full cycle: 42 × 46 min = 32.2 hours
  Usage: ~31.3 credits/day → ~939 credits/month ✓
"""

import logging
import smtplib

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from datetime import datetime, timezone

import config
import database as db
import deal_detector
import notifier
import searcher
from destinations import (
    DOMESTIC_DESTINATIONS, CARIBBEAN_DESTINATIONS, EUROPE_DESTINATIONS,
    SEARCH_PRIORITY,
)
from utils import dates_for_window

log = logging.getLogger(__name__)

TOTAL_SLOTS = len(SEARCH_PRIORITY) * 2  # 42 (21 dests × 2 windows)


# ---------------------------------------------------------------------------
# Scheduler factory
# ---------------------------------------------------------------------------

def create_scheduler() -> BlockingScheduler:
    jobstores = {
        "default": SQLAlchemyJobStore(url=f"sqlite:///{config.DB_PATH}")
    }
    return BlockingScheduler(jobstores=jobstores, timezone="UTC")


# ---------------------------------------------------------------------------
# Core search job
# ---------------------------------------------------------------------------

def _window_for_slot(destination: str, window_idx: int) -> dict:
    """Return the date window for a destination. window_idx 0=near-term, 1=far-out."""
    if destination in DOMESTIC_DESTINATIONS:
        return config.DOMESTIC_DATE_WINDOWS[window_idx]
    if destination in CARIBBEAN_DESTINATIONS:
        return config.CARIBBEAN_DATE_WINDOWS[window_idx]
    if destination in EUROPE_DESTINATIONS:
        return config.EUROPE_DATE_WINDOWS[window_idx]
    return config.MIDDLE_EAST_ASIA_DATE_WINDOWS[window_idx]


def search_job(dry_run: bool = False) -> None:
    """
    Runs every 46 minutes. Scans 1 destination × 1 window per run using a
    persistent sweep_cursor (0–41) that rotates through all 42 slots.
    Sends alerts for any deals found.
    """
    conn = db.get_connection()

    try:
        # Budget check
        if not dry_run and not searcher.is_within_budget(conn):
            return

        # Determine current slot
        cursor     = int(db.get_state(conn, "sweep_cursor", "0"))
        dest_idx   = cursor % len(SEARCH_PRIORITY)
        window_idx = cursor // len(SEARCH_PRIORITY)

        destination  = SEARCH_PRIORITY[dest_idx]
        window       = _window_for_slot(destination, window_idx)
        window_label = "near-term" if window_idx == 0 else "far-out"

        log.info(
            "=== Search job | slot %d/%d | %s [%s] ===",
            cursor + 1, TOTAL_SLOTS, destination, window_label,
        )

        departure_date, return_date = dates_for_window(
            window["offset_weeks"], window["stay_nights"]
        )

        deals_found = []
        smtp_conn: smtplib.SMTP_SSL | None = None

        for origin in config.ORIGINS:
            # Execute search
            response = searcher.execute_search(
                origin=origin,
                destination=destination,
                departure_date=departure_date,
                return_date=return_date,
                dry_run=dry_run,
            )

            # Log API usage (even on dry_run, to test the tracking code)
            db.log_api_call(conn, origin, destination)
            conn.commit()

            if response is None:
                log.warning(
                    "No response for %s→%s %s", origin, destination, departure_date
                )
                continue

            # Extract prices
            prices = searcher.extract_prices(response)

            # Evaluate for deals
            deal = deal_detector.evaluate_search_results(
                conn=conn,
                origin=origin,
                destination=destination,
                departure_date=departure_date,
                return_date=return_date,
                prices=prices,
                dry_run=dry_run,
            )

            if deal:
                deals_found.append((deal, departure_date, return_date))

        # Advance cursor
        next_cursor = (cursor + 1) % TOTAL_SLOTS
        db.set_state(conn, "sweep_cursor", str(next_cursor))
        conn.commit()

        # Send alerts — open one SMTP connection for all alerts in this run
        if deals_found:
            if not dry_run:
                try:
                    smtp_conn = smtplib.SMTP_SSL(notifier.SMTP_HOST, notifier.SMTP_PORT)
                    smtp_conn.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
                except Exception as exc:
                    log.error("SMTP connection failed: %s — alerts will be lost", exc)
                    smtp_conn = None

            for deal, dep_date, ret_date in deals_found:
                success = notifier.send_deal_alert(
                    deal=deal,
                    smtp_conn=smtp_conn,
                    dry_run=dry_run,
                )
                if success and not dry_run:
                    db.record_alert(
                        conn=conn,
                        origin=deal["origin"],
                        destination=deal["destination"],
                        departure_date=dep_date,
                        return_date=ret_date,
                        alerted_price=deal["price"],
                        historical_avg=deal["historical_avg"],
                        pct_below_avg=deal["pct_below"],
                        email_recipient=config.ALERT_RECIPIENT,
                    )
                    conn.commit()

            if smtp_conn:
                smtp_conn.quit()

        log.info(
            "=== Search job complete | slot %d/%d | %s [%s] | %d deals found ===",
            cursor + 1, TOTAL_SLOTS, destination, window_label, len(deals_found),
        )

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Weekly digest job
# ---------------------------------------------------------------------------

def weekly_digest_job(dry_run: bool = False) -> None:
    log.info("Sending weekly digest")
    conn = db.get_connection()
    try:
        notifier.send_weekly_digest(conn, dry_run=dry_run)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Start the scheduler
# ---------------------------------------------------------------------------

def start(dry_run: bool = False) -> None:
    scheduler = create_scheduler()

    scheduler.add_job(
        search_job,
        trigger="interval",
        minutes=46,
        id="flight_search",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),   # run immediately on start
        max_instances=1,
        kwargs={"dry_run": dry_run},
    )

    if config.WEEKLY_DIGEST:
        scheduler.add_job(
            weekly_digest_job,
            trigger="cron",
            day_of_week="mon",
            hour=8,
            minute=0,
            id="weekly_digest",
            replace_existing=True,
            max_instances=1,
            kwargs={"dry_run": dry_run},
        )
        log.info("Weekly digest job registered (Mondays 08:00 UTC)")

    log.info(
        "Scheduler starting — search job runs every 46 min (%d slots, full cycle ~32h)",
        TOTAL_SLOTS,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped")
