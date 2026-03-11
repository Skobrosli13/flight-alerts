"""
Gmail SMTP email notifier.

Sends HTML deal alerts and optional weekly digest emails.
All CSS is inline — Gmail strips <style> tags.
Uses App Password authentication (not OAuth).
"""

import logging
import smtplib
import sqlite3
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
from urllib.parse import quote

import config
import database as db

log = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465   # SSL


# ---------------------------------------------------------------------------
# URL builder
# ---------------------------------------------------------------------------

def build_google_flights_url(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str,
) -> str:
    query = f"Flights from {origin} to {destination} {depart_date} {return_date}"
    return f"https://www.google.com/travel/flights/search?q={quote(query)}"


# ---------------------------------------------------------------------------
# HTML email renderer
# ---------------------------------------------------------------------------

def _format_duration(minutes: int) -> str:
    if not minutes:
        return "—"
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m"


def _format_date(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso)
        return d.strftime("%b %-d, %Y")   # e.g. "Jun 3, 2026"
    except Exception:
        return iso


def render_deal_html(deal: dict) -> str:
    stops_str = "Nonstop" if deal["stops"] == 0 else f"{deal['stops']} stop{'s' if deal['stops'] > 1 else ''}"
    duration_str = _format_duration(deal.get("duration_minutes", 0))
    depart_fmt = _format_date(deal["departure_date"])
    return_fmt = _format_date(deal["return_date"])
    nights = (
        datetime.fromisoformat(deal["return_date"])
        - datetime.fromisoformat(deal["departure_date"])
    ).days
    gf_url = build_google_flights_url(
        deal["origin"], deal["destination"],
        deal["departure_date"], deal["return_date"],
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:20px 0;">
    <tr><td>
      <table width="600" align="center" cellpadding="0" cellspacing="0"
             style="background:#ffffff;border-radius:8px;overflow:hidden;max-width:600px;">

        <!-- Header banner -->
        <tr>
          <td style="background:#1a56db;padding:20px 30px;">
            <p style="margin:0;font-size:11px;color:#a8c4f8;letter-spacing:2px;text-transform:uppercase;">DC Area Flight Deals</p>
            <h1 style="margin:4px 0 0;font-size:22px;color:#ffffff;font-weight:700;">
              ✈ Flight Deal Alert
            </h1>
          </td>
        </tr>

        <!-- Route headline -->
        <tr>
          <td style="padding:24px 30px 0;">
            <h2 style="margin:0;font-size:28px;color:#111827;font-weight:800;">
              {deal["origin"]} &rarr; {deal["destination"]}
            </h2>
            <p style="margin:4px 0 0;font-size:16px;color:#6b7280;">
              {deal["origin_city"]} &rarr; {deal["dest_city"]}
            </p>
          </td>
        </tr>

        <!-- Price card -->
        <tr>
          <td style="padding:20px 30px;">
            <table width="100%" cellpadding="0" cellspacing="0"
                   style="background:#eff6ff;border-radius:8px;border:2px solid #1a56db;">
              <tr>
                <td style="padding:20px 24px;">
                  <p style="margin:0 0 4px;font-size:13px;color:#1a56db;font-weight:600;text-transform:uppercase;letter-spacing:1px;">
                    Round-trip from
                  </p>
                  <p style="margin:0;font-size:52px;font-weight:900;color:#111827;line-height:1;">
                    ${deal["price"]:.0f}
                  </p>
                  <p style="margin:8px 0 0;font-size:15px;color:#374151;">
                    <span style="color:#dc2626;font-weight:700;">{deal["pct_below"]:.0f}% below average</span>
                    &nbsp;&bull;&nbsp; Save ~${deal["savings"]:.0f} vs avg ${deal["historical_avg"]:.0f}
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Trip details -->
        <tr>
          <td style="padding:0 30px 20px;">
            <table width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td width="50%" style="padding:10px 12px;background:#f9fafb;border-radius:6px;">
                  <p style="margin:0;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;">Departs</p>
                  <p style="margin:4px 0 0;font-size:15px;color:#111827;font-weight:600;">{depart_fmt}</p>
                </td>
                <td width="4%"></td>
                <td width="50%" style="padding:10px 12px;background:#f9fafb;border-radius:6px;">
                  <p style="margin:0;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;">Returns</p>
                  <p style="margin:4px 0 0;font-size:15px;color:#111827;font-weight:600;">{return_fmt} &nbsp;({nights} nights)</p>
                </td>
              </tr>
              <tr><td colspan="3" style="height:8px;"></td></tr>
              <tr>
                <td width="50%" style="padding:10px 12px;background:#f9fafb;border-radius:6px;">
                  <p style="margin:0;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;">Airline</p>
                  <p style="margin:4px 0 0;font-size:15px;color:#111827;font-weight:600;">{deal["airline"]}</p>
                </td>
                <td width="4%"></td>
                <td width="50%" style="padding:10px 12px;background:#f9fafb;border-radius:6px;">
                  <p style="margin:0;font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px;">Flight</p>
                  <p style="margin:4px 0 0;font-size:15px;color:#111827;font-weight:600;">{stops_str} &bull; {duration_str}</p>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- Data context -->
        <tr>
          <td style="padding:0 30px 20px;">
            <p style="margin:0;font-size:13px;color:#6b7280;border-left:3px solid #d1d5db;padding-left:12px;">
              Based on <strong>{deal["observation_count"]}</strong> price observations.
              This route averages <strong>${deal["historical_avg"]:.0f}</strong>.
              Lowest recorded: <strong>${deal["historical_min"]:.0f}</strong>.
            </p>
          </td>
        </tr>

        <!-- CTA -->
        <tr>
          <td style="padding:0 30px 30px;text-align:center;">
            <a href="{gf_url}"
               style="display:inline-block;background:#1a56db;color:#ffffff;font-size:16px;
                      font-weight:700;text-decoration:none;padding:14px 32px;
                      border-radius:6px;letter-spacing:0.5px;">
              Search This Deal on Google Flights &rarr;
            </a>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f9fafb;padding:16px 30px;border-top:1px solid #e5e7eb;">
            <p style="margin:0;font-size:12px;color:#9ca3af;text-align:center;">
              Deals checked every 6 hours from IAD &bull; DCA &bull; BWI
              &nbsp;&bull;&nbsp;
              Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def render_deal_text(deal: dict) -> str:
    """Plain-text fallback for email clients that don't render HTML."""
    gf_url = build_google_flights_url(
        deal["origin"], deal["destination"],
        deal["departure_date"], deal["return_date"],
    )
    return (
        f"FLIGHT DEAL ALERT\n"
        f"{'=' * 40}\n\n"
        f"Route:    {deal['origin']} → {deal['destination']} "
        f"({deal['origin_city']} → {deal['dest_city']})\n"
        f"Price:    ${deal['price']:.0f} round-trip\n"
        f"Savings:  {deal['pct_below']:.0f}% below average (avg ${deal['historical_avg']:.0f})\n"
        f"Departs:  {deal['departure_date']}\n"
        f"Returns:  {deal['return_date']}\n"
        f"Airline:  {deal['airline']}\n"
        f"Stops:    {'Nonstop' if deal['stops'] == 0 else deal['stops']}\n\n"
        f"Search:   {gf_url}\n\n"
        f"Based on {deal['observation_count']} observations.\n"
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
    )


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

def send_deal_alert(
    deal: dict,
    smtp_conn: Optional[smtplib.SMTP_SSL] = None,
    dry_run: bool = False,
) -> bool:
    """
    Send a deal alert email. If smtp_conn is provided, reuses the connection
    (efficient when sending multiple alerts in one job run).
    dry_run=True prints to stdout instead of sending.
    Returns True on success.
    """
    subject = (
        f"[DEAL] {deal['origin']} → {deal['destination']} "
        f"from ${deal['price']:.0f} — {deal['pct_below']:.0f}% below avg "
        f"| Departs {deal['departure_date']}"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.GMAIL_ADDRESS
    msg["To"] = config.ALERT_RECIPIENT

    msg.attach(MIMEText(render_deal_text(deal), "plain"))
    msg.attach(MIMEText(render_deal_html(deal), "html"))

    if dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN — Email would be sent:")
        print(f"  To:      {config.ALERT_RECIPIENT}")
        print(f"  Subject: {subject}")
        print("=" * 60)
        print(render_deal_text(deal))
        return True

    try:
        if smtp_conn:
            smtp_conn.send_message(msg)
        else:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as s:
                s.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
                s.send_message(msg)
        log.info("Alert sent: %s→%s $%.0f", deal["origin"], deal["destination"], deal["price"])
        return True
    except Exception as exc:
        log.error("Failed to send alert email: %s", exc)
        return False


def send_weekly_digest(
    conn: sqlite3.Connection,
    dry_run: bool = False,
) -> bool:
    """Send a weekly summary of deals found and API usage."""
    from utils import days_elapsed_in_month

    usage = db.get_monthly_usage(conn)
    deal_count = db.get_monthly_deal_count(conn)
    recent = db.get_recent_alerts(conn, limit=10)
    scanned = db.get_destinations_scanned_this_month(conn)

    pct_used = 100 * usage["total"] / max(config.MONTHLY_BUDGET, 1)
    est_cost = usage["total"] * config.COST_PER_SEARCH

    rows_html = ""
    for a in recent:
        rows_html += (
            f"<tr>"
            f"<td style='padding:6px 10px;'>{a['sent_at'][:10]}</td>"
            f"<td style='padding:6px 10px;font-weight:600;'>{a['origin']}→{a['destination']}</td>"
            f"<td style='padding:6px 10px;color:#dc2626;'>${a['alerted_price']:.0f}</td>"
            f"<td style='padding:6px 10px;'>{a['pct_below_avg']:.0f}% off</td>"
            f"</tr>"
        )

    html = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;color:#111827;max-width:600px;margin:auto;padding:20px;">
  <h2 style="color:#1a56db;">Weekly Flight Alert Digest</h2>
  <table width="100%" style="border-collapse:collapse;background:#f9fafb;border-radius:6px;margin-bottom:20px;">
    <tr><td style="padding:12px 16px;border-bottom:1px solid #e5e7eb;"><strong>API searches used</strong></td>
        <td style="padding:12px 16px;border-bottom:1px solid #e5e7eb;">{usage['total']:,} / {config.MONTHLY_BUDGET:,} ({pct_used:.0f}%)</td></tr>
    <tr><td style="padding:12px 16px;border-bottom:1px solid #e5e7eb;"><strong>Estimated cost this month</strong></td>
        <td style="padding:12px 16px;border-bottom:1px solid #e5e7eb;">${est_cost:.2f}</td></tr>
    <tr><td style="padding:12px 16px;border-bottom:1px solid #e5e7eb;"><strong>Destinations scanned</strong></td>
        <td style="padding:12px 16px;border-bottom:1px solid #e5e7eb;">{scanned} / {len(__import__('destinations').SEARCH_PRIORITY)}</td></tr>
    <tr><td style="padding:12px 16px;"><strong>Deals found this month</strong></td>
        <td style="padding:12px 16px;">{deal_count}</td></tr>
  </table>
  <h3>Recent Alerts</h3>
  <table width="100%" style="border-collapse:collapse;font-size:14px;">
    <tr style="background:#e5e7eb;">
      <th style="padding:6px 10px;text-align:left;">Date</th>
      <th style="padding:6px 10px;text-align:left;">Route</th>
      <th style="padding:6px 10px;text-align:left;">Price</th>
      <th style="padding:6px 10px;text-align:left;">Savings</th>
    </tr>
    {rows_html if rows_html else '<tr><td colspan="4" style="padding:12px;color:#9ca3af;">No deals found yet</td></tr>'}
  </table>
  <p style="font-size:12px;color:#9ca3af;margin-top:24px;">
    Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")} &bull; IAD/DCA/BWI Deal Alerter
  </p>
</body></html>"""

    subject = f"Weekly Flight Alert Digest — {deal_count} deal{'s' if deal_count != 1 else ''} found"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.GMAIL_ADDRESS
    msg["To"] = config.ALERT_RECIPIENT
    msg.attach(MIMEText(html, "html"))

    if dry_run:
        print(f"\nDRY RUN — Weekly digest would be sent: {subject}")
        return True

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as s:
            s.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
            s.send_message(msg)
        log.info("Weekly digest sent")
        return True
    except Exception as exc:
        log.error("Failed to send weekly digest: %s", exc)
        return False
