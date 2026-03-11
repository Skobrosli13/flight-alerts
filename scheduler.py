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
    WEEKEND_DATE_DESTINATIONS, SEARCH_PRIORITY,
)
from utils import dates_for_window

log = logging.getLogger(__name__)

def _build_scan_slots() -> list[dict]:
    """
    Build the full ordered flat list of scan slots.
    East coast destinations (MIA, BOS) get 8 slots each (4 date combos × 2 booking windows).
    All other destinations get 2 slots each (near-term + far-out).
    Total: 19×2 + 2×8 = 54 slots. Full cycle: 54 × 46 min = 41.4 hours.
    """
    slots = []
    for dest in SEARCH_PRIORITY:
        if dest in WEEKEND_DATE_DESTINATIONS:
            for w in config.WEEKEND_DATE_WINDOWS:
                slots.append({"dest": dest, **w})
        else:
            for window_idx in range(2):
                if dest in DOMESTIC_DESTINATIONS:
                    w = config.DOMESTIC_DATE_WINDOWS[window_idx]
                elif dest in EUROPE_DESTINATIONS:
                    w = config.EUROPE_DATE_WINDOWS[window_idx]
                else:
                    w = config.MIDDLE_EAST_ASIA_DATE_WINDOWS[window_idx]
                label = "Near-term" if window_idx == 0 else "Far-out"
                slots.append({"dest": dest, "label": label, **w})
    return slots


SCAN_SLOTS  = _build_scan_slots()
TOTAL_SLOTS = len(SCAN_SLOTS)   # 54: 19×2 + 2×8


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
    Runs every 46 minutes. Scans 1 destination × 1 window per run using a
    persistent sweep_cursor (0–53) that rotates through all 54 slots.
    Sends alerts for any deals found.
    """
    conn = db.get_connection()

    try:
        # Budget check
        if not dry_run and not searcher.is_within_budget(conn):
            return

        # Determine current slot
        cursor = int(db.get_state(conn, "sweep_cursor", "0"))
        slot   = SCAN_SLOTS[cursor % TOTAL_SLOTS]

        destination  = slot["dest"]
        window_label = slot["label"]

        log.info(
            "=== Search job | slot %d/%d | %s [%s] ===",
            cursor + 1, TOTAL_SLOTS, destination, window_label,
        )

        departure_date, return_date = dates_for_window(
            slot["offset_weeks"], slot["stay_nights"],
            departure_weekday=slot.get("departure_weekday", 4),
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
