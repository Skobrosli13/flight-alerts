"""
SQLite database setup and all query/insert functions.
Every other module imports from here — init_database() must run first.
"""

import sqlite3
import logging
from datetime import datetime, timezone
from typing import Optional

import config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # better concurrency
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

def init_database() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS price_history (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                origin         TEXT    NOT NULL,
                destination    TEXT    NOT NULL,
                departure_date TEXT    NOT NULL,
                return_date    TEXT    NOT NULL,
                price_usd      REAL    NOT NULL,
                cabin_class    TEXT    NOT NULL DEFAULT 'economy',
                observed_at    TEXT    NOT NULL,
                data_source    TEXT    NOT NULL DEFAULT 'serpapi',
                UNIQUE(origin, destination, departure_date, return_date, observed_at)
            );

            CREATE INDEX IF NOT EXISTS idx_history_route
                ON price_history(origin, destination, departure_date);

            CREATE TABLE IF NOT EXISTS sent_alerts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                origin          TEXT    NOT NULL,
                destination     TEXT    NOT NULL,
                departure_date  TEXT    NOT NULL,
                return_date     TEXT    NOT NULL,
                alerted_price   REAL    NOT NULL,
                historical_avg  REAL    NOT NULL,
                pct_below_avg   REAL    NOT NULL,
                sent_at         TEXT    NOT NULL,
                email_recipient TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_alerts_route
                ON sent_alerts(origin, destination, departure_date, sent_at);

            CREATE TABLE IF NOT EXISTS scheduler_state (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS api_usage (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                called_at    TEXT NOT NULL,
                origin       TEXT NOT NULL,
                destination  TEXT NOT NULL,
                credits_used INTEGER NOT NULL DEFAULT 1
            );

            CREATE INDEX IF NOT EXISTS idx_api_usage_date
                ON api_usage(called_at);
        """)
    log.info("Database initialised at %s", config.DB_PATH)


# ---------------------------------------------------------------------------
# price_history
# ---------------------------------------------------------------------------

def insert_price(
    conn: sqlite3.Connection,
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str,
    price_usd: float,
    cabin_class: str = "economy",
) -> None:
    observed_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT OR IGNORE INTO price_history
            (origin, destination, departure_date, return_date,
             price_usd, cabin_class, observed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (origin, destination, departure_date, return_date,
         price_usd, cabin_class, observed_at),
    )


def get_price_stats(
    conn: sqlite3.Connection,
    origin: str,
    destination: str,
    departure_date: str,
    date_window_days: int,
    lookback_days: int,
) -> Optional[dict]:
    """
    Returns {'mean': float, 'std': float, 'count': int, 'min': float}
    for a route over a date window and lookback period, or None if no data.
    """
    row = conn.execute(
        """
        SELECT
            AVG(price_usd)  AS mean,
            -- SQLite has no STDEV; approximate via variance formula
            SQRT(AVG(price_usd * price_usd) - AVG(price_usd) * AVG(price_usd)) AS std,
            COUNT(*)        AS cnt,
            MIN(price_usd)  AS min_price
        FROM price_history
        WHERE origin         = ?
          AND destination    = ?
          AND departure_date BETWEEN date(?, '-' || ? || ' days')
                                 AND date(?, '+' || ? || ' days')
          AND observed_at   >= date('now', '-' || ? || ' days')
        """,
        (
            origin, destination,
            departure_date, date_window_days,
            departure_date, date_window_days,
            lookback_days,
        ),
    ).fetchone()

    if row is None or row["cnt"] == 0:
        return None

    return {
        "mean":  row["mean"],
        "std":   row["std"] or 0.0,
        "count": row["cnt"],
        "min":   row["min_price"],
    }


# ---------------------------------------------------------------------------
# sent_alerts
# ---------------------------------------------------------------------------

def was_recently_alerted(
    conn: sqlite3.Connection,
    origin: str,
    destination: str,
    departure_date: str,
    cooldown_days: int,
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM sent_alerts
        WHERE origin         = ?
          AND destination    = ?
          AND departure_date = ?
          AND sent_at       >= date('now', '-' || ? || ' days')
        LIMIT 1
        """,
        (origin, destination, departure_date, cooldown_days),
    ).fetchone()
    return row is not None


def record_alert(
    conn: sqlite3.Connection,
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str,
    alerted_price: float,
    historical_avg: float,
    pct_below_avg: float,
    email_recipient: str,
) -> None:
    sent_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO sent_alerts
            (origin, destination, departure_date, return_date,
             alerted_price, historical_avg, pct_below_avg, sent_at, email_recipient)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (origin, destination, departure_date, return_date,
         alerted_price, historical_avg, pct_below_avg, sent_at, email_recipient),
    )


# ---------------------------------------------------------------------------
# scheduler_state (rotation cursor)
# ---------------------------------------------------------------------------

def get_state(conn: sqlite3.Connection, key: str, default: str = "0") -> str:
    row = conn.execute(
        "SELECT value FROM scheduler_state WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO scheduler_state (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value, now),
    )


# ---------------------------------------------------------------------------
# api_usage
# ---------------------------------------------------------------------------

def log_api_call(
    conn: sqlite3.Connection,
    origin: str,
    destination: str,
    credits_used: int = 1,
) -> None:
    called_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO api_usage (called_at, origin, destination, credits_used)
        VALUES (?, ?, ?, ?)
        """,
        (called_at, origin, destination, credits_used),
    )


def get_monthly_usage(conn: sqlite3.Connection) -> dict:
    """Returns total searches this calendar month, broken down by origin."""
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).isoformat()

    total_row = conn.execute(
        "SELECT COALESCE(SUM(credits_used), 0) AS total FROM api_usage WHERE called_at >= ?",
        (month_start,),
    ).fetchone()

    by_origin = conn.execute(
        """
        SELECT origin, COALESCE(SUM(credits_used), 0) AS total
        FROM api_usage
        WHERE called_at >= ?
        GROUP BY origin
        ORDER BY total DESC
        """,
        (month_start,),
    ).fetchall()

    return {
        "total": int(total_row["total"]),
        "by_origin": {row["origin"]: int(row["total"]) for row in by_origin},
        "month_start": month_start,
    }


def get_monthly_search_count(conn: sqlite3.Connection) -> int:
    return get_monthly_usage(conn)["total"]


# ---------------------------------------------------------------------------
# Monitoring helpers
# ---------------------------------------------------------------------------

def get_recent_alerts(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    rows = conn.execute(
        """
        SELECT origin, destination, departure_date, return_date,
               alerted_price, historical_avg, pct_below_avg, sent_at
        FROM sent_alerts
        ORDER BY sent_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_monthly_deal_count(conn: sqlite3.Connection) -> int:
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM sent_alerts WHERE sent_at >= ?",
        (month_start,),
    ).fetchone()
    return int(row["cnt"])


def get_last_scan_time(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute(
        "SELECT MAX(called_at) AS last FROM api_usage"
    ).fetchone()
    return row["last"] if row else None


def get_destinations_scanned_this_month(
    conn: sqlite3.Connection,
    active_destinations: list[str] | None = None,
) -> int:
    month_start = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    if active_destinations:
        placeholders = ",".join("?" * len(active_destinations))
        row = conn.execute(
            f"SELECT COUNT(DISTINCT destination) AS cnt FROM api_usage "
            f"WHERE called_at >= ? AND destination IN ({placeholders})",
            [month_start] + list(active_destinations),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(DISTINCT destination) AS cnt FROM api_usage WHERE called_at >= ?",
            (month_start,),
        ).fetchone()
    return int(row["cnt"]) if row else 0
