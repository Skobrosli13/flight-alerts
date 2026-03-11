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
# Search windows: (weeks_from_today, stay_nights)
# Two windows to stay within 1,000-search/month Starter plan budget.
# Upgrade to 4 windows on a higher plan by adding entries here.
# ---------------------------------------------------------------------------
DATE_WINDOWS = [
    {"offset_weeks": 4,  "stay_nights": 7},
    {"offset_weeks": 10, "stay_nights": 10},
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
