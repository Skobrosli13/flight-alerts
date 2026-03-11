"""
Shared utilities: logging setup, date helpers, retry decorator.
"""

import logging
import time
import random
import functools
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(level: str = "INFO", log_file: str = "") -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def departure_date_for_window(offset_weeks: int, preferred_weekday: int = 4) -> str:
    """Return ISO date string for a departure offset_weeks from today.
    preferred_weekday: 0=Mon … 6=Sun (default 4=Friday).
    """
    d = date.today() + timedelta(weeks=offset_weeks)
    days_to_target = (preferred_weekday - d.weekday()) % 7
    d += timedelta(days=days_to_target)
    return d.isoformat()


def return_date_for_window(departure_iso: str, stay_nights: int) -> str:
    """Return ISO date string for return date given departure + stay length."""
    d = date.fromisoformat(departure_iso) + timedelta(days=stay_nights)
    return d.isoformat()


def dates_for_window(
    offset_weeks: int, stay_nights: int, departure_weekday: int = 4
) -> tuple[str, str]:
    depart = departure_date_for_window(offset_weeks, departure_weekday)
    ret = return_date_for_window(depart, stay_nights)
    return depart, ret


def month_start_iso() -> str:
    """ISO date string for the first day of the current month."""
    today = date.today()
    return today.replace(day=1).isoformat()


def days_remaining_in_month() -> int:
    today = date.today()
    # Last day of month: go to first day of next month and subtract 1
    if today.month == 12:
        last = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        last = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
    return (last - today).days + 1


def days_elapsed_in_month() -> int:
    return date.today().day


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def retry(max_attempts: int = 3, base_delay: float = 10.0, jitter: float = 5.0):
    """
    Decorator that retries a function on exception with exponential back-off.
    Backs off: base_delay * 2^attempt + uniform(0, jitter) seconds.
    Returns None (not raises) after all attempts are exhausted.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            log = logging.getLogger(fn.__module__)
            for attempt in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    wait = base_delay * (2 ** attempt) + random.uniform(0, jitter)
                    if attempt < max_attempts - 1:
                        log.warning(
                            "%s failed (attempt %d/%d): %s — retrying in %.1fs",
                            fn.__name__, attempt + 1, max_attempts, exc, wait,
                        )
                        time.sleep(wait)
                    else:
                        log.error(
                            "%s failed after %d attempts: %s",
                            fn.__name__, max_attempts, exc,
                        )
            return None
        return wrapper
    return decorator
