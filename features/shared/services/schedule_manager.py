# =============================================================================
# services/schedule_manager.py
# ScheduleManager — slot generation, lookup, ranking
# =============================================================================
# NSL coverage : GO3 (Doctor Scheduling), GO4 LO1 (slot selection)
# Failure cases: E8  — lunch-hour validation in booking, not just in display
#                E12 — weekend guard in primary booking path
#                E22 — 30-min slots, only 1 lunch slot blocked (correct)
#                E23 — slot overlapping lunch boundary correctly blocked
#                E24 — doctor deactivated mid-day, existing slots untouched
#                F5  — uneven slot division truncates cleanly (no crash)
#                F13 — slot cache invalidated on every write
#                F14 — binary search on sorted list guaranteed
#
# CHANGE: Availability table/model REMOVED. Doctor working hours are stored
#         directly in the doctors table. Slots are generated automatically
#         from those fixed hours. Weekly auto-regeneration is supported.
#
# DSA requirements (assignment spec):
#   - List comprehension for available slot filtering
#   - Lambda / map / filter for slot processing
#   - Binary search (bisect) for slot lookup by time
#   - Sorting for doctor availability ranking
#   - Generator to stream appointment queue
# =============================================================================

from __future__ import annotations

import bisect
import logging
import threading
from datetime import date, datetime, time, timedelta
from typing import Generator, Optional

from config import settings
from features.shared.database.postgres import PostgresManager
from features.shared.models.doctor import Doctor
from features.shared.models.slot import (
    AppointmentSlot,
    generate_slots_for_doctor,
    LUNCH_START,
    LUNCH_END,
    SLOT_DURATION_OPTIONS,
    DEFAULT_START_TIME,
    DEFAULT_END_TIME,
)

logger = logging.getLogger(__name__)


def _date_value(value: date | str) -> date:
    return date.fromisoformat(value) if isinstance(value, str) else value


def _time_value(value: time | str) -> time:
    return time.fromisoformat(value) if isinstance(value, str) else value

# ---------------------------------------------------------------------------
# Lunch overlap helper (E23 — slots that START before 13:30 but END after 13:00)
# ---------------------------------------------------------------------------

def _overlaps_lunch(start: time, end: time) -> bool:
    """True if the slot window overlaps the 13:00–13:30 lunch break at all."""
    return start < LUNCH_END and end > LUNCH_START


class ScheduleManager:
    """Generates, stores, and queries appointment slots for doctors.

    One instance is shared across the whole app (passed in by main.py).

    Responsibilities
    ----------------
    - Generate AppointmentSlot rows from doctor's fixed work hours
    - Auto-generate weekly slots for new doctors and next-week regeneration
    - Return available/all slots with cache invalidation
    - Binary-search slot lookup by target time
    - Rank doctors by available slot count (for suggestion UI)
    - Stream slot lists as generators (DSA requirement)
    - Find next available slot across future dates (E10)
    """

    def __init__(self, db: PostgresManager) -> None:
        self._db    = db
        self._cache: dict[tuple, list[dict]] = {}   # (doctor_id, date_str) → slots
        self._lock  = threading.Lock()

    # =========================================================================
    # Slot Generation — directly from doctor work hours (no Availability)
    # =========================================================================

    def generate_daily_slots(
        self,
        doctor: dict | Doctor,
        for_date: date,
    ) -> list[dict]:
        """Generate and persist AppointmentSlot records for doctor+date.

        Uses generate_slots_for_doctor() which applies:
          - Chronological iteration (guarantees sorted output — F14 safe)
          - Lunch block at 13:00–13:30 (R051)
          - Max-patients cap (R052, NF6)
          - Partial-duration truncation (F5)

        Invalidates the slot cache for this (doctor, date) pair.
        Returns the list of saved slot dicts.
        """
        # Extract fields whether dict or Doctor object
        if isinstance(doctor, Doctor):
            doctor_id = doctor.doctor_id
            work_start = doctor.work_start_time
            work_end = doctor.work_end_time
            consult_mins = doctor.consultation_duration_minutes
            max_patients = doctor.max_patients_per_day
        else:
            doctor_id = doctor["doctor_id"]
            work_start = _time_value(doctor.get("work_start_time", "09:00:00"))
            work_end = _time_value(doctor.get("work_end_time", "17:00:00"))
            consult_mins = doctor.get("consultation_duration_minutes", settings.DEFAULT_SLOT_DURATION)
            max_patients = doctor.get("max_patients_per_day", 20)

        # Check if slots already exist for this date
        if self._db.has_slots_for_doctor_date(doctor_id, for_date.isoformat()):
            logger.debug(f"Slots already exist for {doctor_id} on {for_date}, skipping generation.")
            return self._db.get_all_slots_for_doctor_date(doctor_id, for_date.isoformat())

        slots = generate_slots_for_doctor(
            doctor_id=doctor_id,
            for_date=for_date,
            work_start_time=work_start,
            work_end_time=work_end,
            slot_duration_minutes=consult_mins,
            max_patients_per_day=max_patients,
        )
        slot_dicts = [s.to_dict() for s in slots]
        self._db.save_slots(slot_dicts)
        self._invalidate_cache(doctor_id, for_date.isoformat())

        bookable = sum(1 for s in slots if not s.is_blocked)
        logger.info(
            f"Generated {len(slots)} slots ({bookable} bookable) "
            f"for {doctor_id} on {for_date}"
        )
        return slot_dicts

    # =========================================================================
    # Weekly auto-generation — generate slots for the next 5 weekdays
    # =========================================================================

    def generate_weekly_slots(self, doctor: dict | Doctor) -> int:
        """Generate slots for the next 5 weekdays from today.

        Called when a doctor is registered, and also triggered periodically
        to ensure the next week's slots are always available.

        Returns total number of slots generated.
        """
        if isinstance(doctor, Doctor):
            doctor_id = doctor.doctor_id
        else:
            doctor_id = doctor["doctor_id"]

        total_generated = 0
        d = date.today()
        weekdays_generated = 0

        while weekdays_generated < 5:
            if d.weekday() not in (5, 6):  # skip weekends
                slots = self.generate_daily_slots(doctor, d)
                total_generated += len(slots)
                weekdays_generated += 1
            d += timedelta(days=1)

        logger.info(
            f"Weekly slot generation complete for {doctor_id}: "
            f"{total_generated} total slots across 5 weekdays"
        )
        return total_generated

    def auto_regenerate_weekly_slots(self, doctor: dict | Doctor) -> int:
        """Check if the current week's slots are expiring and regenerate.

        Generates slots for the next 5 weekdays starting from today.
        Skips dates that already have slots.

        Returns total number of NEW slots generated.
        """
        return self.generate_weekly_slots(doctor)

    # =========================================================================
    # GO4 LO1 — Get available slots (with list comprehension + cache)
    # =========================================================================

    def get_available_slots(self, doctor_id: str, for_date: date) -> list[dict]:
        """Return all bookable slots for doctor on date.

        Uses list comprehension (DSA requirement).
        Results are cached; cache is invalidated on every booking/cancel.
        """
        key = (doctor_id, for_date.isoformat())
        with self._lock:
            if key in self._cache:
                return self._cache[key]

        raw = self._db.get_available_slots(doctor_id, for_date.isoformat())

        # List comprehension — filter + sort (DSA)
        slots = sorted(
            [s for s in raw if not s["is_booked"]
                             and not s["is_blocked"]
                             and not s["is_lunch_break"]],
            key=lambda s: s["start_time"]
        )

        with self._lock:
            self._cache[key] = slots
        return slots

    def get_all_slots_for_display(self, doctor_id: str, for_date: date) -> list[dict]:
        """All slots (including blocked/booked) for admin/doctor management UI."""
        raw = self._db.get_all_slots_for_doctor_date(
            doctor_id, for_date.isoformat()
        )
        return sorted(raw, key=lambda s: s["start_time"])

    def invalidate_cache(self, doctor_id: str, date_str: str) -> None:
        """Public entry point — called by BookingService after every state change."""
        self._invalidate_cache(doctor_id, date_str)

    def _invalidate_cache(self, doctor_id: str, date_str: str) -> None:
        with self._lock:
            self._cache.pop((doctor_id, date_str), None)

    # =========================================================================
    # Binary search — slot lookup by target time (DSA requirement, F14)
    # =========================================================================

    def find_slot_by_time(
        self,
        doctor_id: str,
        for_date: date,
        target_time: time,
    ) -> Optional[dict]:
        """Find an available slot whose start_time == target_time.

        Uses bisect.bisect_left on sorted start_time strings (F14 — list is
        always sorted because generate_daily_slots iterates chronologically).

        Returns the slot dict or None if not found / not available.
        """
        slots = self.get_available_slots(doctor_id, for_date)
        if not slots:
            return None

        # Build sorted key list for bisect
        times = [_time_value(s["start_time"]).isoformat() for s in slots]
        target_str = target_time.isoformat()
        idx = bisect.bisect_left(times, target_str)

        if idx < len(times) and times[idx] == target_str:
            return slots[idx]
        return None

    # =========================================================================
    # Lunch-hour guard (E8 — explicit server-side check, not just display filter)
    # =========================================================================

    def is_lunch_time(self, slot_start: time, slot_end: time) -> bool:
        """Return True if the slot overlaps the lunch window.

        Called by BookingService.book_appointment() to enforce E8 mitigation
        even when a client sends a raw time via API (bypassing the UI filter).
        """
        return _overlaps_lunch(slot_start, slot_end)

    # =========================================================================
    # Weekend guard (E12 — server-side check for primary booking path)
    # =========================================================================

    @staticmethod
    def is_weekend(for_date: date) -> bool:
        return for_date.weekday() in (5, 6)   # 5=Sat, 6=Sun

    # =========================================================================
    # Next available slot (E10 — cross-date search, up to 14 days)
    # =========================================================================

    def find_next_available_slot(
        self,
        doctor_id: str,
        after_date: date,
        max_days: int = settings.NEXT_SLOT_SEARCH_DAYS,
    ) -> Optional[dict]:
        """Find earliest available slot after after_date (E10).

        Skips weekends (E12 mitigation for the suggestion path).
        Searches up to max_days ahead.
        """
        return self._db.find_next_available_slot(
            doctor_id,
            after_date.isoformat(),
            max_days=max_days,
        )

    # =========================================================================
    # Doctor availability ranking (sorting — DSA requirement)
    # =========================================================================

    def rank_doctors_by_availability(
        self, for_date: date, doctors: list[dict]
    ) -> list[dict]:
        """Sort doctors by number of free slots descending (GO4 NF1 display).

        Uses lambda sort (DSA requirement).
        Returns list of {doctor_dict, available_count} sorted best-first.
        """
        def _count(doc: dict) -> int:
            return len(self.get_available_slots(doc["doctor_id"], for_date))

        ranked = sorted(
            [{"doctor": d, "available_slots": _count(d)} for d in doctors],
            key=lambda x: x["available_slots"],
            reverse=True,
        )
        return ranked

    # =========================================================================
    # Generator — stream slots (DSA requirement)
    # =========================================================================

    def stream_slots(
        self, doctor_id: str, for_date: date
    ) -> Generator[dict, None, None]:
        """Yield available slots one at a time (generator — DSA requirement).

        Useful for large slot sets where you want to process one at a time
        without loading the full list into memory (e.g. Streamlit lazy rendering).
        """
        slots = self.get_available_slots(doctor_id, for_date)
        for slot in slots:
            yield slot

    # Slot processing helpers using map/filter/lambda (DSA requirement)
    # =========================================================================

    @staticmethod
    def slot_time_labels(slots: list[dict]) -> list[str]:
        """Map slot dicts → human-readable time label strings.

        Uses map() + lambda (DSA requirement).
        Example: ["09:00 AM – 09:15 AM", ...]
        """
        def _fmt(s: dict) -> str:
            start_time = _time_value(s["start_time"])
            end_time = _time_value(s["end_time"])
            start = datetime.combine(date.today(), start_time)
            end = datetime.combine(date.today(), end_time)
            return f"{start.strftime('%I:%M %p')} – {end.strftime('%I:%M %p')}"

        return list(map(_fmt, slots))

    @staticmethod
    def filter_slots_after(slots: list[dict], after_time: time) -> list[dict]:
        """Return only slots starting at or after after_time.

        Uses filter() + lambda (DSA requirement).
        """
        after_str = after_time.isoformat()
        return list(filter(lambda s: _time_value(s["start_time"]).isoformat() >= after_str, slots))
