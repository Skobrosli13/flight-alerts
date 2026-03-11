"""
APScheduler setup and the main search_job function.

Uses BlockingScheduler (runs as a long-lived daemon process).
Job state is persisted in flights.db via SQLAlchemyJobStore so restarts
resume correctly without losing rotation position.
"""

import logging
import smtplib
import sqlite3

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from datetime import datetime, timezone

import config
import database as db
import deal_detector
import notifier
import searcher
from destinations import DOMESTIC_DESTINATIONS, EUROPE_CARIBBEAN_DESTINATIONS
from utils import dates_for_window

log = logging.getLogger(__name__)


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

def search_job(dry_run: bool = False) -> None:
    """
    Runs every 6 hours. Searches the next batch of destinations across all
    3 DC-area origins and 4 date windows. Sends alerts for any deals found.
    """
    log.info("=== Search job started ===")
    conn = db.get_connection()

    try:
        # Budget check
        if not dry_run and not searcher.is_within_budget(conn):
            return

        # Get next batch of destinations
        destinations = searcher.get_next_batch(conn)
        conn.commit()

        deals_found = []
        smtp_conn: smtplib.SMTP_SSL | None = None

        for destination in destinations:
            if destination in DOMESTIC_DESTINATIONS:
                windows = config.DOMESTIC_DATE_WINDOWS
            elif destination in EUROPE_CARIBBEAN_DESTINATIONS:
                windows = config.EUROPE_CARIBBEAN_DATE_WINDOWS
            else:
                windows = config.MIDDLE_EAST_ASIA_DATE_WINDOWS
            for window in windows:
                departure_date, return_date = dates_for_window(
                    window["offset_weeks"], window["stay_nights"]
                )

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

        # Send alerts — open one SMTP connection for all alerts in this run
        if deals_found:
            if not dry_run:
                try:
                    smtp_conn = smtplib.SMTP_SSL(notifier.SMTP_HOST, notifier.SMTP_PORT)
                    smtp_conn.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
                except Exception as exc:
                    log.error("SMTP connection failed: %s — alerts will be lost", exc)
                    smtp_conn = None

            for deal, departure_date, return_date in deals_found:
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
                        departure_date=departure_date,
                        return_date=return_date,
                        alerted_price=deal["price"],
                        historical_avg=deal["historical_avg"],
                        pct_below_avg=deal["pct_below"],
                        email_recipient=config.ALERT_RECIPIENT,
                    )
                    conn.commit()

            if smtp_conn:
                smtp_conn.quit()

        log.info(
            "=== Search job complete | %d destinations | %d deals found ===",
            len(destinations), len(deals_found),
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
        hours=6,
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

    log.info("Scheduler starting — search job runs every 6 hours")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped")
