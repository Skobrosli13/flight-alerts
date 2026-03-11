"""
Central configuration for the Flight Deal Alerter.
All values can be overridden via environment variables (see .env.example).
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            f"Copy .env.example to .env and fill in your credentials."
        )
    return val


# ---------------------------------------------------------------------------
# API credentials (required — hard fail if missing)
# ---------------------------------------------------------------------------
SERPAPI_KEY = _require("SERPAPI_KEY")
GMAIL_ADDRESS = _require("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = _require("GMAIL_APP_PASSWORD")
ALERT_RECIPIENT = _require("ALERT_RECIPIENT")

# ---------------------------------------------------------------------------
# Origins (DC-area airports, always searched)
# ---------------------------------------------------------------------------
ORIGINS = ["IAD", "DCA", "BWI"]

# ---------------------------------------------------------------------------
# API budget control
# Starter plan: 1,000 searches/month → ~950 usable (50 buffer)
# Budget math: 950 / 120 jobs/month ≈ 8 searches per job
#   1 destination × 3 origins × 2 date windows = 6 searches/job ✓
#   Full rotation: 26 destinations × 6h ≈ 6.5 days per sweep
# ---------------------------------------------------------------------------
MONTHLY_BUDGET = int(os.getenv("MONTHLY_BUDGET", "950"))        # search credits
SEARCHES_PER_JOB = int(os.getenv("SEARCHES_PER_JOB", "6"))      # per 6-hour run
COST_PER_SEARCH = float(os.getenv("COST_PER_SEARCH", "0.01"))   # $ per credit
MONTHLY_BUDGET_USD = float(os.getenv("MONTHLY_BUDGET_USD", "50.00"))

# ---------------------------------------------------------------------------
# Deal detection
# ---------------------------------------------------------------------------
DEAL_THRESHOLD = float(os.getenv("DEAL_THRESHOLD", "0.40"))         # 40% below avg
MIN_OBSERVATIONS = int(os.getenv("MIN_OBSERVATIONS", "10"))          # cold-start guard
ALERT_COOLDOWN_DAYS = int(os.getenv("ALERT_COOLDOWN_DAYS", "7"))
STATS_DATE_WINDOW = int(os.getenv("STATS_DATE_WINDOW", "14"))        # ±days for query
STATS_LOOKBACK_DAYS = int(os.getenv("STATS_LOOKBACK_DAYS", "90"))

# ---------------------------------------------------------------------------
# Search windows: split by destination type.
# Domestic routes book near-term; international requires advance planning.
# Both sets use 2 windows → 6 credits/run unchanged (720/month).
# ---------------------------------------------------------------------------
DOMESTIC_DATE_WINDOWS = [
    {"offset_weeks": 2,  "stay_nights": 4},   # ~2 weeks out, long weekend
    {"offset_weeks": 6,  "stay_nights": 7},   # ~6 weeks out, week trip
]
EUROPE_CARIBBEAN_DATE_WINDOWS = [
    {"offset_weeks": 14, "stay_nights": 7},   # ~3.5 months out, 1-week trip
    {"offset_weeks": 30, "stay_nights": 7},   # ~7 months out, 1-week trip
]
MIDDLE_EAST_ASIA_DATE_WINDOWS = [
    {"offset_weeks": 14, "stay_nights": 10},  # ~3.5 months out, 10-night trip
    {"offset_weeks": 30, "stay_nights": 14},  # ~7 months out, 2-week trip
]

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_PATH = os.getenv("DB_PATH", "flights.db")

# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
WEEKLY_DIGEST = os.getenv("WEEKLY_DIGEST", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "")  # empty = stdout only
