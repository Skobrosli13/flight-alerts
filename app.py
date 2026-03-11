"""
Flask web dashboard for the DC Flight Deal Alerter.

Run with:  python app.py
Then open:  http://localhost:5000
"""

import os
import sys
import threading
from datetime import datetime

from flask import Flask, render_template, jsonify, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ---------------------------------------------------------------------------
# Load project modules — may fail if .env is not yet configured
# ---------------------------------------------------------------------------
try:
    import config
    import database as db
    from destinations import DESTINATIONS, AIRPORT_NAMES, SEARCH_PRIORITY
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

GROUP_LABELS = {
    "domestic_tier1":   "Domestic Tier 1",
    "caribbean_mexico": "Caribbean & Mexico",
    "europe_tier1":     "Europe Tier 1",
    "europe_tier2":     "Europe Tier 2",
    "middle_east":      "Middle East",
    "asia_pacific":     "Asia-Pacific",
}


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
        dests_scanned  = db.get_destinations_scanned_this_month(conn)

        total_obs = int(conn.execute(
            "SELECT COUNT(*) AS cnt FROM price_history"
        ).fetchone()["cnt"])

        batch_cursor  = int(db.get_state(conn, "batch_cursor", "0"))
        next_dest     = SEARCH_PRIORITY[batch_cursor % len(SEARCH_PRIORITY)]
        budget        = config.MONTHLY_BUDGET
        monthly_usage = usage["total"]
        budget_pct    = round(monthly_usage / budget * 100, 1) if budget else 0

    finally:
        conn.close()

    return render_template(
        "dashboard.html",
        monthly_usage=monthly_usage,
        budget=budget,
        budget_pct=budget_pct,
        monthly_deals=monthly_deals,
        total_observations=total_obs,
        recent_alerts=recent_alerts,
        last_scan=last_scan,
        dests_scanned=dests_scanned,
        total_destinations=len(SEARCH_PRIORITY),
        origin_usage=usage["by_origin"],
        next_destination=next_dest,
        next_dest_name=AIRPORT_NAMES.get(next_dest, next_dest),
        batch_cursor=batch_cursor,
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
        usage     = db.get_monthly_usage(conn)
        last_scan = db.get_last_scan_time(conn)
    finally:
        conn.close()

    budget = config.MONTHLY_BUDGET
    used   = usage["total"]
    return jsonify({
        "monthly_usage": used,
        "budget":        budget,
        "remaining":     budget - used,
        "pct_used":      round(used / budget * 100, 1) if budget else 0,
        "last_scan":     last_scan,
        "timestamp":     datetime.now().isoformat(),
    })


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
