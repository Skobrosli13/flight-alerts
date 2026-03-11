"""
Flask web dashboard for the DC Flight Deal Alerter.

Run with:  python app.py
Then open:  http://localhost:5000
"""

import json
import logging
import os
import sys
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import quote as url_quote
from zoneinfo import ZoneInfo

_EASTERN = ZoneInfo("America/New_York")

from flask import Flask, render_template, jsonify, request

log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ---------------------------------------------------------------------------
# Load project modules — may fail if .env is not yet configured
# ---------------------------------------------------------------------------
try:
    import config
    import database as db
    from destinations import (
        DESTINATIONS, AIRPORT_NAMES, SEARCH_PRIORITY,
        DOMESTIC_DESTINATIONS, EUROPE_DESTINATIONS,
        WEEKEND_DATE_DESTINATIONS,
    )
    SETUP_OK = True
    SETUP_ERROR = None
except EnvironmentError as e:
    SETUP_OK = False
    SETUP_ERROR = str(e)
    config = None
    db = None
    DESTINATIONS = {}
    AIRPORT_NAMES = {}
    SEARCH_PRIORITY = []
    DOMESTIC_DESTINATIONS = set()
    EUROPE_DESTINATIONS = set()
    WEEKEND_DATE_DESTINATIONS = set()

GROUP_LABELS = {
    "domestic_tier1":   "Domestic Tier 1",
    "caribbean_mexico": "Caribbean & Mexico",
    "europe_tier1":     "Europe Tier 1",
    "europe_tier2":     "Europe Tier 2",
    "middle_east":      "Middle East",
    "asia_pacific":     "Asia-Pacific",
}


def _build_scan_slots() -> list[dict]:
    """Mirror of scheduler._build_scan_slots — kept in sync manually."""
    if not SEARCH_PRIORITY:
        return []
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
TOTAL_SLOTS = len(SCAN_SLOTS)  # 72: 5×8 + 16×2


# ---------------------------------------------------------------------------
# SerpApi live account data (cached 5 minutes)
# ---------------------------------------------------------------------------
_serpapi_cache: dict = {"data": None, "fetched_at": None}
_CACHE_TTL = 300  # seconds


def get_serpapi_account() -> dict | None:
    """Fetch live credit usage from SerpApi account endpoint. Cached for 5 min."""
    now = datetime.now()
    cached_at = _serpapi_cache["fetched_at"]
    if cached_at is None or (now - cached_at).total_seconds() > _CACHE_TTL:
        try:
            url = f"https://serpapi.com/account.json?api_key={config.SERPAPI_KEY}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                _serpapi_cache["data"] = json.loads(resp.read())
                _serpapi_cache["fetched_at"] = now
        except Exception as exc:
            log.warning("Failed to fetch SerpApi account data: %s", exc)
    return _serpapi_cache["data"]


@app.template_filter("eastern")
def to_eastern(dt_str: str) -> str:
    """Convert a UTC ISO datetime string to Eastern time (ET/EDT) for display."""
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_EASTERN).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return dt_str[:16].replace("T", " ")


@app.template_global()
def flights_url(origin: str, destination: str, depart_date: str, return_date: str) -> str:
    query = f"Flights from {origin} to {destination} {depart_date} {return_date}"
    return f"https://www.google.com/travel/flights/search?q={url_quote(query)}"


def require_setup(f):
    from functools import wraps
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not SETUP_OK:
            return render_template("setup.html", error=SETUP_ERROR), 503
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
@require_setup
def dashboard():
    conn = db.get_connection()
    try:
        usage          = db.get_monthly_usage(conn)
        monthly_deals  = db.get_monthly_deal_count(conn)
        recent_alerts  = db.get_recent_alerts(conn, limit=5)
        last_scan      = db.get_last_scan_time(conn)
        dests_scanned  = db.get_destinations_scanned_this_month(conn, SEARCH_PRIORITY)

        total_obs = int(conn.execute(
            "SELECT COUNT(*) AS cnt FROM price_history"
        ).fetchone()["cnt"])

        sweep_cursor = int(db.get_state(conn, "sweep_cursor", "0"))
        next_slot    = SCAN_SLOTS[sweep_cursor % TOTAL_SLOTS]
        next_dest    = next_slot["dest"]

    finally:
        conn.close()

    account = get_serpapi_account()
    if account:
        monthly_usage = int(account.get("this_month_usage", usage["total"]))
        budget        = int(account.get("plan_monthly_searches", config.MONTHLY_BUDGET))
        plan_name     = account.get("plan_name", "")
        credits_source = "Live from SerpApi"
    else:
        monthly_usage = usage["total"]
        budget        = config.MONTHLY_BUDGET
        plan_name     = ""
        credits_source = "Local estimate"

    budget_pct = round(monthly_usage / budget * 100, 1) if budget else 0

    return render_template(
        "dashboard.html",
        monthly_usage=monthly_usage,
        budget=budget,
        budget_pct=budget_pct,
        plan_name=plan_name,
        credits_source=credits_source,
        monthly_deals=monthly_deals,
        total_observations=total_obs,
        recent_alerts=recent_alerts,
        last_scan=last_scan,
        dests_scanned=dests_scanned,
        total_destinations=len(SEARCH_PRIORITY),
        origin_usage=usage["by_origin"],
        sweep_cursor=sweep_cursor,
        total_slots=TOTAL_SLOTS,
        next_destination=next_dest,
        next_dest_name=AIRPORT_NAMES.get(next_dest, next_dest),
        next_window_label=next_slot["label"],
    )


@app.route("/destinations")
@require_setup
def destinations():
    conn = db.get_connection()
    try:
        rows = conn.execute("""
            SELECT destination,
                   COUNT(*)              AS obs_count,
                   ROUND(AVG(price_usd), 0) AS avg_price,
                   MIN(price_usd)        AS min_price,
                   MAX(observed_at)      AS last_seen
            FROM price_history
            GROUP BY destination
        """).fetchall()
    finally:
        conn.close()

    dest_stats = {r["destination"]: dict(r) for r in rows}

    return render_template(
        "destinations.html",
        destinations=DESTINATIONS,
        group_labels=GROUP_LABELS,
        airport_names=AIRPORT_NAMES,
        dest_stats=dest_stats,
        min_observations=config.MIN_OBSERVATIONS,
    )


@app.route("/history")
@require_setup
def history():
    dest   = request.args.get("dest", "")
    origin = request.args.get("origin", config.ORIGINS[0])

    history_data = []
    if dest:
        conn = db.get_connection()
        try:
            rows = conn.execute("""
                SELECT origin, departure_date, return_date,
                       price_usd, observed_at, data_source
                FROM price_history
                WHERE destination = ? AND origin = ?
                ORDER BY observed_at ASC
                LIMIT 500
            """, (dest, origin)).fetchall()
        finally:
            conn.close()
        history_data = [dict(r) for r in rows]

    return render_template(
        "history.html",
        destinations=SEARCH_PRIORITY,
        airport_names=AIRPORT_NAMES,
        origins=config.ORIGINS,
        selected_dest=dest,
        selected_origin=origin,
        dest_name=AIRPORT_NAMES.get(dest, dest),
        history_data=history_data,
    )


@app.route("/alerts")
@require_setup
def alerts():
    conn = db.get_connection()
    try:
        rows = conn.execute("""
            SELECT origin, destination, departure_date, return_date,
                   alerted_price, historical_avg, pct_below_avg,
                   sent_at, email_recipient
            FROM sent_alerts
            ORDER BY sent_at DESC
            LIMIT 200
        """).fetchall()
    finally:
        conn.close()

    return render_template(
        "alerts.html",
        alerts=[dict(r) for r in rows],
        airport_names=AIRPORT_NAMES,
    )


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.route("/api/status")
@require_setup
def api_status():
    conn = db.get_connection()
    try:
        last_scan = db.get_last_scan_time(conn)
        local_used = db.get_monthly_usage(conn)["total"]
    finally:
        conn.close()

    account = get_serpapi_account()
    if account:
        used   = int(account.get("this_month_usage", local_used))
        budget = int(account.get("plan_monthly_searches", config.MONTHLY_BUDGET))
        plan   = account.get("plan_name", "Unknown")
        source = "serpapi"
    else:
        used   = local_used
        budget = config.MONTHLY_BUDGET
        plan   = None
        source = "local"

    # Compute next scan time: last_scan + 46 min (scheduler interval)
    next_scan_at = None
    if last_scan:
        try:
            ls_dt = datetime.fromisoformat(last_scan.replace("Z", "+00:00"))
            if ls_dt.tzinfo is None:
                ls_dt = ls_dt.replace(tzinfo=timezone.utc)
            next_scan_at = (ls_dt + timedelta(minutes=46)).isoformat()
        except Exception:
            pass

    return jsonify({
        "monthly_usage": used,
        "budget":        budget,
        "remaining":     budget - used,
        "pct_used":      round(used / budget * 100, 1) if budget else 0,
        "plan":          plan,
        "source":        source,
        "last_scan":     last_scan,
        "next_scan_at":  next_scan_at,
        "timestamp":     datetime.now().isoformat(),
    })


@app.route("/schedule")
@require_setup
def schedule():
    conn = db.get_connection()
    try:
        sweep_cursor = int(db.get_state(conn, "sweep_cursor", "0"))
        last_scan    = db.get_last_scan_time(conn)
    finally:
        conn.close()

    now = datetime.now(timezone.utc)
    if last_scan:
        try:
            ls_dt = datetime.fromisoformat(last_scan.replace("Z", "+00:00"))
            if ls_dt.tzinfo is None:
                ls_dt = ls_dt.replace(tzinfo=timezone.utc)
            next_fire = ls_dt + timedelta(minutes=46)
            if next_fire < now:
                next_fire = now
        except Exception:
            next_fire = now
    else:
        next_fire = now

    def _group(dest):
        for group, codes in DESTINATIONS.items():
            if dest in codes:
                return GROUP_LABELS.get(group, group)
        return ""

    slots = []
    for i in range(TOTAL_SLOTS):
        slot_idx = (sweep_cursor + i) % TOTAL_SLOTS
        slot     = SCAN_SLOTS[slot_idx]
        dest     = slot["dest"]
        eta      = next_fire + timedelta(minutes=46 * i)
        slots.append({
            "queue_pos":    i + 1,
            "destination":  dest,
            "dest_name":    AIRPORT_NAMES.get(dest, dest),
            "group":        _group(dest),
            "window_label": slot["label"],
            "offset_weeks": slot["offset_weeks"],
            "stay_nights":  slot["stay_nights"],
            "eta":          eta.isoformat(),
            "is_next":      i == 0,
        })

    return render_template(
        "schedule.html",
        slots=slots,
        sweep_cursor=sweep_cursor,
        total_slots=TOTAL_SLOTS,
    )


@app.route("/api/trigger", methods=["POST"])
@require_setup
def trigger_job():
    data    = request.get_json(silent=True) or {}
    dry_run = data.get("dry_run", True)

    def run():
        from scheduler import search_job
        search_job(dry_run=dry_run)

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "started", "dry_run": dry_run})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if SETUP_OK:
        db.init_database()
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=5000, debug=debug, use_reloader=False)
