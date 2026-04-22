# =============================================================================
# models/slot.py
# TimeSlot dataclass and AppointmentSlot
# =============================================================================
# NSL reference: GO3 (Define Doctor Availability) entity definitions
#
# Two related types live here:
#   TimeSlot        — lightweight (start, end) pair, used by ScheduleManager
#   AppointmentSlot — one bookable slot generated from doctor work hours
#
# Lunch block: 13:00–13:30 is flagged automatically (NSL NF4, R051)
#
# NOTE: Availability class has been REMOVED. Doctor working hours are now
#       stored directly in the doctors table and slots are generated from
#       those fixed timings.
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Optional
from uuid import uuid4


# ---------------------------------------------------------------------------
# Lunch break constants (NSL R051 — must always be blocked)
# ---------------------------------------------------------------------------

LUNCH_START: time = time(13, 0)   # 1:00 PM
LUNCH_END:   time = time(13, 30)  # 1:30 PM

SLOT_DURATION_OPTIONS: list[int] = [10, 15, 20, 30]  # minutes (NSL enum)

DEFAULT_START_TIME: time = time(9, 0)   # 9:00 AM
DEFAULT_END_TIME:   time = time(17, 0)  # 5:00 PM


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_lunch_slot(slot_start: time) -> bool:
    """True if a slot starts within the lunch window (13:00–13:29)."""
    return LUNCH_START <= slot_start < LUNCH_END


def _next_slot_id() -> str:
    return str(uuid4())


# ---------------------------------------------------------------------------
# TimeSlot — simple (start, end) value object used internally
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TimeSlot:
    """Immutable (start_time, end_time) pair.

    Used by ScheduleManager for arithmetic — not persisted directly.

    Attributes
    ----------
    start_time : time
    end_time   : time
    """

    start_time: time
    end_time: time

    def __post_init__(self) -> None:
        if self.start_time >= self.end_time:
            raise ValueError(
                f"TimeSlot start ({self.start_time}) must be before end ({self.end_time})."
            )

    @property
    def duration_minutes(self) -> int:
        """Duration as whole minutes."""
        start_dt = datetime.combine(date.today(), self.start_time)
        end_dt   = datetime.combine(date.today(), self.end_time)
        return int((end_dt - start_dt).total_seconds() // 60)

    def overlaps(self, other: "TimeSlot") -> bool:
        """True if two TimeSlots overlap (used for conflict detection)."""
        return self.start_time < other.end_time and other.start_time < self.end_time

    def __str__(self) -> str:
        fmt = "%I:%M %p"
        return (
            f"{self.start_time.strftime(fmt)} – {self.end_time.strftime(fmt)}"
        )


# ---------------------------------------------------------------------------
# AppointmentSlot — one bookable (or blocked) time window (GO3 LO2)
# ---------------------------------------------------------------------------

class AppointmentSlot:
    """A single time slot for a doctor on a given date.

    Created automatically by generate_slots_for_doctor().
    Only is_booked and is_blocked change after creation (R053).

    Attributes
    ----------
    slot_id       : str  — UUID
    is_lunch_break: bool — True if slot falls in 13:00–13:30
    is_booked     : bool — True once a patient reserves this slot
    is_blocked    : bool — True for lunch + max-cap overflow slots
    """

    def __init__(
        self,
        doctor_id: str,
        date: date,
        start_time: time,
        end_time: time,
        is_lunch_break: bool = False,
        is_booked: bool = False,
        is_blocked: bool = False,
        slot_id: Optional[str] = None,
    ) -> None:
        self.doctor_id:        str  = doctor_id
        self.date:             date = date
        self.start_time:       time = start_time
        self.end_time:         time = end_time

        if start_time >= end_time:
            raise ValueError(
                f"Slot start_time ({start_time}) must be before end_time ({end_time})."
            )
        
        self.is_lunch_break:   bool = is_lunch_break
        self.is_booked:        bool = is_booked
        self.is_blocked:       bool = is_blocked

        self.slot_id: str = slot_id or _next_slot_id()

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """True only if slot can be booked right now."""
        return not self.is_booked and not self.is_blocked and not self.is_lunch_break

    def book(self) -> None:
        """Mark slot as booked. Raises if already taken."""
        if self.is_booked:
            raise ValueError(f"Slot {self.slot_id} is already booked.")
        if self.is_blocked:
            raise ValueError(f"Slot {self.slot_id} is blocked (lunch or cap overflow).")
        self.is_booked = True

    def release(self) -> None:
        """Release slot back to available (on cancellation / reschedule)."""
        self.is_booked = False

    @property
    def as_time_slot(self) -> TimeSlot:
        """Convert to lightweight TimeSlot for overlap checks."""
        return TimeSlot(start_time=self.start_time, end_time=self.end_time)

    # ------------------------------------------------------------------
    # Magic methods
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        status = "BOOKED" if self.is_booked else ("BLOCKED" if self.is_blocked else "FREE")
        return (
            f"AppointmentSlot("
            f"slot_id={self.slot_id!r}, "
            f"date={self.date}, "
            f"time={self.start_time}–{self.end_time}, "
            f"status={status}"
            f")"
        )

    def __str__(self) -> str:
        fmt = "%I:%M %p"
        flag = " [LUNCH]" if self.is_lunch_break else ""
        flag += " [BLOCKED]" if self.is_blocked and not self.is_lunch_break else ""
        flag += " ✓ BOOKED" if self.is_booked else ""
        return (
            f"{self.date} | {self.start_time.strftime(fmt)} – "
            f"{self.end_time.strftime(fmt)}{flag}"
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "slot_id":          self.slot_id,
            "doctor_id":        self.doctor_id,
            "date":             self.date.isoformat(),
            "start_time":       self.start_time.isoformat(),
            "end_time":         self.end_time.isoformat(),
            "is_lunch_break":   self.is_lunch_break,
            "is_booked":        self.is_booked,
            "is_blocked":       self.is_blocked,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AppointmentSlot":
        return cls(
            doctor_id=data["doctor_id"],
            date=date.fromisoformat(data["date"]) if isinstance(data["date"], str) else data["date"],
            start_time=time.fromisoformat(data["start_time"]) if isinstance(data["start_time"], str) else data["start_time"],
            end_time=time.fromisoformat(data["end_time"]) if isinstance(data["end_time"], str) else data["end_time"],
            is_lunch_break=data.get("is_lunch_break", False),
            is_booked=data.get("is_booked", False),
            is_blocked=data.get("is_blocked", False),
            slot_id=data.get("slot_id"),
        )


# ---------------------------------------------------------------------------
# Slot generation — creates slots directly from doctor work hours
# ---------------------------------------------------------------------------

def generate_slots_for_doctor(
    doctor_id: str,
    for_date: date,
    work_start_time: time,
    work_end_time: time,
    slot_duration_minutes: int,
    max_patients_per_day: int,
) -> list[AppointmentSlot]:
    """Generate AppointmentSlot list directly from doctor work hours.

    This replaces the old Availability.generate_slots() approach.
    Doctor working hours are now stored in the doctors table itself
    and are fixed for every day.

    Applies:
    - Lunch block (NF4 / R051)
    - max_patients cap (NF6 / R052)

    Parameters
    ----------
    doctor_id             : Doctor's UUID
    for_date              : The date to generate slots for
    work_start_time       : Doctor's work start time
    work_end_time         : Doctor's work end time
    slot_duration_minutes : Duration of each slot
    max_patients_per_day  : Maximum bookable slots per day
    """
    slots: list[AppointmentSlot] = []
    current = datetime.combine(for_date, work_start_time)
    end_dt  = datetime.combine(for_date, work_end_time)
    duration = timedelta(minutes=slot_duration_minutes)

    bookable_count = 0

    while current + duration <= end_dt:
        s_time = current.time()
        e_time = (current + duration).time()
        is_lunch = _is_lunch_slot(s_time)

        # Max patients cap (NF6): block excess slots
        if not is_lunch and bookable_count >= max_patients_per_day:
            is_blocked = True
        else:
            is_blocked = is_lunch  # lunch slots are always blocked

        slot = AppointmentSlot(
            doctor_id=doctor_id,
            date=for_date,
            start_time=s_time,
            end_time=e_time,
            is_lunch_break=is_lunch,
            is_blocked=is_blocked,
        )
        slots.append(slot)

        if not is_lunch and not is_blocked:
            bookable_count += 1

        current += duration

    return slots
