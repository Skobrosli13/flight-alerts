"""
CLI monitoring dashboard.

Run any time: python monitor.py

Prints a terminal report covering:
  - API usage and cost for the current month
  - Projected month-end usage
  - Coverage (destinations scanned)
  - Deals found and recent alert history
"""

import sys
from datetime import datetime, timezone

import config
import database as db
from destinations import SEARCH_PRIORITY
from utils import days_elapsed_in_month, days_remaining_in_month


# ---------------------------------------------------------------------------
# Data gathering
# ---------------------------------------------------------------------------

def _monthly_usage(conn) -> dict:
    return db.get_monthly_usage(conn)


def _projected_month_end(usage_total: int) -> int:
    elapsed = max(days_elapsed_in_month(), 1)
    remaining = days_remaining_in_month()
    daily_rate = usage_total / elapsed
    return int(usage_total + daily_rate * remaining)


def _budget_bar(used: int, budget: int, width: int = 30) -> str:
    pct = min(used / max(budget, 1), 1.0)
    filled = int(pct * width)
    bar = "█" * filled + "░" * (width - filled)
    color = ""
    if pct >= 0.90:
        color = "\033[91m"   # red
    elif pct >= 0.75:
        color = "\033[93m"   # yellow
    else:
        color = "\033[92m"   # green
    reset = "\033[0m"
    return f"{color}[{bar}]{reset} {pct*100:.0f}%"


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def print_report(conn) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    month_label = datetime.now(timezone.utc).strftime("%B %Y")

    usage = _monthly_usage(conn)
    total = usage["total"]
    budget = config.MONTHLY_BUDGET
    est_cost = total * config.COST_PER_SEARCH
    projected = _projected_month_end(total)
    days_left = days_remaining_in_month()

    deal_count = db.get_monthly_deal_count(conn)
    recent_alerts = db.get_recent_alerts(conn, limit=10)
    scanned = db.get_destinations_scanned_this_month(conn)
    last_scan = db.get_last_scan_time(conn)
    total_dests = len(SEARCH_PRIORITY)

    budget_status = "✓ within budget" if projected <= budget else "⚠ may exceed budget"

    sep = "=" * 56

    print(f"\n{sep}")
    print("  Flight Deal Alerter — Status Report")
    print(f"  Generated: {now}")
    print(sep)

    print(f"\nAPI USAGE THIS MONTH ({month_label})")
    print(f"  Searches used:       {total:,} / {budget:,}")
    print(f"  {_budget_bar(total, budget)}")
    print(f"  Estimated cost:      ${est_cost:.2f}  (@ ${config.COST_PER_SEARCH}/search)")
    print(f"  Days remaining:      {days_left}")
    print(f"  Projected month-end: {projected:,} searches  — {budget_status}")

    if usage["by_origin"]:
        print(f"\n  By origin airport:")
        for origin in config.ORIGINS:
            count = usage["by_origin"].get(origin, 0)
            print(f"    {origin}:  {count:,} searches")

    print(f"\nCOVERAGE")
    print(f"  Destinations scanned this month: {scanned} / {total_dests}")
    if total > 0:
        # Estimate avg days between sweeps based on rotation math
        searches_per_dest = total / max(scanned, 1)
        days_per_sweep = (total_dests / max(total / max(days_elapsed_in_month(), 1), 1))
        print(f"  Est. days between full sweeps:   {days_per_sweep:.1f} days")
    print(f"  Last scan:                       {last_scan or 'Never'}")

    print(f"\nDEALS")
    print(f"  Deals found this month:  {deal_count}")
    if recent_alerts:
        last = recent_alerts[0]
        print(f"  Last alert:              {last['origin']}→{last['destination']}  "
              f"${last['alerted_price']:.0f} ({last['pct_below_avg']:.0f}% off)  "
              f"sent {last['sent_at'][:10]}")

    if recent_alerts:
        print(f"\nRECENT ALERTS (last {len(recent_alerts)})")
        print(f"  {'Date':<12} {'Route':<12} {'Price':>7} {'Savings':>9}")
        print(f"  {'-'*12} {'-'*12} {'-'*7} {'-'*9}")
        for a in recent_alerts:
            route = f"{a['origin']}→{a['destination']}"
            print(
                f"  {a['sent_at'][:10]:<12} {route:<12} "
                f"${a['alerted_price']:>6.0f} {a['pct_below_avg']:>8.0f}% off"
            )
    else:
        print(f"\nRECENT ALERTS")
        print("  No alerts sent yet.")

    print(f"\n{sep}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    db.init_database()
    conn = db.get_connection()
    try:
        print_report(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
