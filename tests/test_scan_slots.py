"""
Tests for the scan slot schedule — validates that no credits are wasted.

Checks:
  - Correct total slot count (72)
  - Weekend destinations (MIA, BOS, CUN, MBJ, PUJ) get exactly 8 slots each
  - Every weekend slot has a departure weekday of Thu(3) or Fri(4)
  - Every weekend slot produces a valid return on Sun(6) or Mon(0)
  - Non-weekend domestic (LAX, ORD, LAS) get exactly 2 slots each
  - Europe destinations get exactly 2 slots each
  - Middle East / Asia-Pacific destinations get exactly 2 slots each
  - scheduler and app produce identical slot lists
  - deal_detector weekend guard accepts all weekend slot date combos

Run: pytest tests/test_scan_slots.py -v
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("SERPAPI_KEY",        "test")
os.environ.setdefault("GMAIL_ADDRESS",      "test@example.com")
os.environ.setdefault("GMAIL_APP_PASSWORD", "test")
os.environ.setdefault("ALERT_RECIPIENT",    "test@example.com")

from datetime import date, timedelta

import config
import deal_detector
import scheduler
import app as flask_app
from destinations import (
    SEARCH_PRIORITY, DOMESTIC_DESTINATIONS, EUROPE_DESTINATIONS,
    WEEKEND_DATE_DESTINATIONS,
)
from utils import dates_for_window

WEEKEND_DESTS    = {"MIA", "BOS", "CUN", "MBJ", "PUJ"}
NON_WEEKEND_DOM  = {"LAX", "ORD", "LAS"}
EUROPE_DESTS     = {"LHR", "CDG", "FCO", "BCN", "LIS", "MAD"}
MIDEAST_ASIA     = {"BEY", "TLV", "IST", "CAI", "NRT", "BKK", "SYD"}

EXPECTED_TOTAL   = 72   # 5×8 + 16×2


class TestSlotCount:
    def test_scheduler_total_slots(self):
        assert scheduler.TOTAL_SLOTS == EXPECTED_TOTAL, (
            f"scheduler has {scheduler.TOTAL_SLOTS} slots, expected {EXPECTED_TOTAL}"
        )

    def test_app_total_slots(self):
        assert flask_app.TOTAL_SLOTS == EXPECTED_TOTAL, (
            f"app has {flask_app.TOTAL_SLOTS} slots, expected {EXPECTED_TOTAL}"
        )

    def test_scheduler_and_app_slots_match(self):
        """Both modules must produce identical slot lists for consistent cursor indexing."""
        s_slots = scheduler.SCAN_SLOTS
        a_slots = flask_app.SCAN_SLOTS
        assert len(s_slots) == len(a_slots)
        for i, (s, a) in enumerate(zip(s_slots, a_slots)):
            assert s == a, f"Slot {i} mismatch: scheduler={s}  app={a}"


class TestWeekendDestinationSlots:
    def test_each_weekend_dest_has_8_slots(self):
        slot_counts = {d: 0 for d in WEEKEND_DESTS}
        for slot in scheduler.SCAN_SLOTS:
            if slot["dest"] in WEEKEND_DESTS:
                slot_counts[slot["dest"]] += 1
        for dest, count in slot_counts.items():
            assert count == 8, f"{dest} has {count} slots, expected 8"

    def test_weekend_slots_have_valid_departure_weekday(self):
        """Every weekend slot must depart on Thu(3) or Fri(4)."""
        for slot in scheduler.SCAN_SLOTS:
            if slot["dest"] in WEEKEND_DESTS:
                dw = slot.get("departure_weekday")
                assert dw in {3, 4}, (
                    f"{slot['dest']} slot has departure_weekday={dw}, expected 3 or 4"
                )

    def test_weekend_slots_produce_valid_return_day(self):
        """Every weekend slot, when dates_for_window is called, must return on Sun(6) or Mon(0)."""
        for slot in scheduler.SCAN_SLOTS:
            if slot["dest"] in WEEKEND_DESTS:
                _, ret_iso = dates_for_window(
                    slot["offset_weeks"],
                    slot["stay_nights"],
                    departure_weekday=slot["departure_weekday"],
                )
                ret_dow = date.fromisoformat(ret_iso).weekday()
                assert ret_dow in {6, 0}, (
                    f"{slot['dest']} slot (depart_wd={slot['departure_weekday']}, "
                    f"stay={slot['stay_nights']}n) returns on weekday {ret_dow}, "
                    f"expected Sunday(6) or Monday(0). Return date: {ret_iso}"
                )

    def test_weekend_slots_produce_valid_departure_day(self):
        """Every weekend slot must actually depart on Thu or Fri."""
        for slot in scheduler.SCAN_SLOTS:
            if slot["dest"] in WEEKEND_DESTS:
                dep_iso, _ = dates_for_window(
                    slot["offset_weeks"],
                    slot["stay_nights"],
                    departure_weekday=slot["departure_weekday"],
                )
                dep_dow = date.fromisoformat(dep_iso).weekday()
                assert dep_dow in {3, 4}, (
                    f"{slot['dest']} slot has departure on weekday {dep_dow}, "
                    f"expected Thursday(3) or Friday(4). Departure date: {dep_iso}"
                )

    def test_deal_detector_weekend_guard_accepts_all_weekend_slots(self):
        """deal_detector's EAST_COAST_DESTINATIONS guard must pass for every weekend slot's dates."""
        for slot in scheduler.SCAN_SLOTS:
            dest = slot["dest"]
            if dest not in deal_detector.EAST_COAST_DESTINATIONS:
                continue
            dep_iso, ret_iso = dates_for_window(
                slot["offset_weeks"],
                slot["stay_nights"],
                departure_weekday=slot["departure_weekday"],
            )
            dep_dow = date.fromisoformat(dep_iso).weekday()
            ret_dow = date.fromisoformat(ret_iso).weekday()
            assert dep_dow in deal_detector.WEEKEND_DEPART_DAYS, (
                f"{dest}: departure weekday {dep_dow} not in WEEKEND_DEPART_DAYS"
            )
            assert ret_dow in deal_detector.WEEKEND_RETURN_DAYS, (
                f"{dest}: return weekday {ret_dow} not in WEEKEND_RETURN_DAYS"
            )


class TestNonWeekendSlots:
    def test_domestic_other_gets_2_slots(self):
        for dest in NON_WEEKEND_DOM:
            count = sum(1 for s in scheduler.SCAN_SLOTS if s["dest"] == dest)
            assert count == 2, f"{dest} has {count} slots, expected 2"

    def test_europe_gets_2_slots(self):
        for dest in EUROPE_DESTS:
            count = sum(1 for s in scheduler.SCAN_SLOTS if s["dest"] == dest)
            assert count == 2, f"{dest} has {count} slots, expected 2"

    def test_mideast_asia_gets_2_slots(self):
        for dest in MIDEAST_ASIA:
            count = sum(1 for s in scheduler.SCAN_SLOTS if s["dest"] == dest)
            assert count == 2, f"{dest} has {count} slots, expected 2"

    def test_non_weekend_domestic_stay_is_4_nights(self):
        for slot in scheduler.SCAN_SLOTS:
            if slot["dest"] in NON_WEEKEND_DOM:
                assert slot["stay_nights"] == 4, (
                    f"{slot['dest']} has stay_nights={slot['stay_nights']}, expected 4"
                )

    def test_non_weekend_domestic_labels(self):
        """Non-weekend slots must have Near-term / Far-out labels."""
        labels_seen = {dest: set() for dest in NON_WEEKEND_DOM}
        for slot in scheduler.SCAN_SLOTS:
            if slot["dest"] in NON_WEEKEND_DOM:
                labels_seen[slot["dest"]].add(slot["label"])
        for dest, labels in labels_seen.items():
            assert labels == {"Near-term", "Far-out"}, (
                f"{dest} has labels {labels}"
            )


class TestAllDestsPresent:
    def test_every_search_priority_dest_in_slots(self):
        dests_in_slots = {s["dest"] for s in scheduler.SCAN_SLOTS}
        for dest in SEARCH_PRIORITY:
            assert dest in dests_in_slots, f"{dest} missing from SCAN_SLOTS"

    def test_no_extra_dests_in_slots(self):
        dests_in_slots = {s["dest"] for s in scheduler.SCAN_SLOTS}
        assert dests_in_slots == set(SEARCH_PRIORITY)
