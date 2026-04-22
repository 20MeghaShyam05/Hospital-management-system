# =============================================================================
# models/appointment.py
# Appointment entity + status/priority enums
# =============================================================================
# NSL reference: GO4 (Book), GO5 (Cancel), GO6 (Reschedule) entity defs
# Fields: appointment_id, patient_id, doctor_id, slot_id, date,
#         start_time, end_time, status, priority, notes,
#         booked_at, booked_by, cancellation_reason, cancelled_by,
#         cancelled_at, reschedule_count
# Business Rules: R071–R082, R091–R102, R111–R122
# =============================================================================

from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from typing import Optional
import html as _html
from uuid import uuid4

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AppointmentStatus(str, Enum):
    BOOKED      = "booked"
    COMPLETED   = "completed"
    CANCELLED   = "cancelled"
    NO_SHOW     = "no-show"
    RESCHEDULED = "rescheduled"   # transient — immediately becomes BOOKED

    # Valid transitions (used by _validate_transition)
    @classmethod
    def allowed_transitions(cls) -> dict["AppointmentStatus", set["AppointmentStatus"]]:
        return {
            cls.BOOKED:      {cls.COMPLETED, cls.CANCELLED, cls.NO_SHOW, cls.RESCHEDULED},
            cls.RESCHEDULED: {cls.BOOKED},
            cls.COMPLETED:   set(),   # terminal
            cls.CANCELLED:   set(),   # terminal
            cls.NO_SHOW:     set(),   # terminal
        }


class AppointmentPriority(str, Enum):
    NORMAL    = "normal"
    EMERGENCY = "emergency"


def _next_appointment_id() -> str:
    return f"HMS-APT-{date.today():%Y%m%d}-{uuid4().hex[:6].upper()}"


# ---------------------------------------------------------------------------
# Appointment class
# ---------------------------------------------------------------------------

class Appointment:
    """A confirmed appointment between a patient and a doctor.

    Lifecycle
    ---------
    booked → completed
           → cancelled
           → no-show
           → rescheduled → booked (same object, new slot details)

    Business Rules Enforced Here
    ----------------------------
    R071  — double booking guard (slot must not already be booked)
    R074  — emergency priority triggers priority queue (flag only; QueueManager acts)
    R091  — can only cancel future appointments
    R092  — cancellation reason >= 10 chars
    R100  — status transition: booked → cancelled
    R111  — reschedule_count < 2 (max 2 reschedules, R120)
    R122  — reschedule is atomic (handled by BookingService; model tracks count)
    """

    def __init__(
        self,
        patient_id: str,
        doctor_id: str,
        slot_id: str,
        date: date,
        start_time: time,
        end_time: time,
        priority: AppointmentPriority = AppointmentPriority.NORMAL,
        notes: Optional[str] = None,
        booked_by: Optional[str] = None,   # session user ID
        appointment_id: Optional[str] = None,
        calendar_event_id: Optional[str] = None,
        calendar_event_link: Optional[str] = None,
    ) -> None:
        self.patient_id:  str  = patient_id
        self.doctor_id:   str  = doctor_id
        self.slot_id:     str  = slot_id
        self.date:        date = date
        self.start_time:  time = start_time
        self.end_time:    time = end_time

        if start_time >= end_time:
            raise ValueError(
                f"Appointment start_time ({start_time}) must be before end_time ({end_time})."
            )
        
        self.priority:    AppointmentPriority = priority
        
        if notes:
            cleaned = _html.escape(notes.strip())   # neutralise < > & " '
            self.notes = cleaned[:500]
        else:
            self.notes = None
        
        self.booked_by:   Optional[str] = booked_by
        self.booked_at:   datetime = datetime.now()

        # Status — always starts as BOOKED
        self._status: AppointmentStatus = AppointmentStatus.BOOKED

        # Cancellation fields (populated only on cancellation)
        self.cancellation_reason: Optional[str] = None
        self.cancelled_by:        Optional[str] = None
        self.cancelled_at:        Optional[datetime] = None

        # Reschedule tracking (R111 / R120)
        self.reschedule_count: int = 0

        self.appointment_id: str = appointment_id or _next_appointment_id()
        self.calendar_event_id: Optional[str] = calendar_event_id
        self.calendar_event_link: Optional[str] = calendar_event_link

    # ------------------------------------------------------------------
    # Status management
    # ------------------------------------------------------------------

    @property
    def status(self) -> AppointmentStatus:
        return self._status

    def _validate_transition(self, new_status: AppointmentStatus) -> None:
        allowed = AppointmentStatus.allowed_transitions().get(self._status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition appointment from '{self._status.value}' "
                f"to '{new_status.value}'."
            )

    def cancel(self, reason: str, cancelled_by: Optional[str] = None) -> None:
        """Cancel this appointment (R091, R092, R100).

        Parameters
        ----------
        reason       : must be >= 10 characters (R092)
        cancelled_by : session user ID
        """
        self._validate_transition(AppointmentStatus.CANCELLED)

        # R091 — cannot cancel past appointments
        if self.date < date.today():
            raise ValueError("Cannot cancel an appointment that has already passed.")

        # R092 — reason must be descriptive
        if not reason or len(reason.strip()) < 10:
            raise ValueError("Please provide a more detailed cancellation reason (min 10 chars).")

        self._status              = AppointmentStatus.CANCELLED
        self.cancellation_reason  = reason.strip()
        self.cancelled_by         = cancelled_by
        self.cancelled_at         = datetime.now()

    def complete(self) -> None:
        """Mark appointment as completed (called by QueueManager LO3)."""
        self._validate_transition(AppointmentStatus.COMPLETED)
        self._status = AppointmentStatus.COMPLETED

    def mark_no_show(self) -> None:
        """Mark patient as a no-show (called by QueueManager LO3)."""
        self._validate_transition(AppointmentStatus.NO_SHOW)
        self._status = AppointmentStatus.NO_SHOW

    def reschedule(
        self,
        new_slot_id: str,
        new_date: date,
        new_start_time: time,
        new_end_time: time,
    ) -> None:
        """Update appointment to a new slot (GO6 LO3).

        R111 / R120 — max 2 reschedules.
        R121 — same doctor is enforced at the service layer.
        """
        self._validate_transition(AppointmentStatus.RESCHEDULED)

        if self.reschedule_count >= 2:
            raise ValueError(
                "Maximum reschedule limit reached. Please cancel and rebook."
            )

        self._status       = AppointmentStatus.RESCHEDULED
        self.slot_id       = new_slot_id
        self.date          = new_date
        self.start_time    = new_start_time
        self.end_time      = new_end_time
        self.reschedule_count += 1

        # Return to BOOKED immediately (R122 transient state)
        self._status = AppointmentStatus.BOOKED

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def is_emergency(self) -> bool:
        return self.priority == AppointmentPriority.EMERGENCY

    @property
    def is_active(self) -> bool:
        """True if appointment is still open (booked or rescheduled)."""
        return self._status == AppointmentStatus.BOOKED

    def appointment_datetime(self) -> datetime:
        """Full datetime of appointment start (for sorting / display)."""
        return datetime.combine(self.date, self.start_time)

    # ------------------------------------------------------------------
    # Magic methods
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Appointment("
            f"appointment_id={self.appointment_id!r}, "
            f"patient_id={self.patient_id!r}, "
            f"doctor_id={self.doctor_id!r}, "
            f"date={self.date}, "
            f"time={self.start_time}–{self.end_time}, "
            f"status={self._status.value!r}, "
            f"priority={self.priority.value!r}"
            f")"
        )

    def __str__(self) -> str:
        fmt = "%I:%M %p"
        priority_flag = " 🚨 EMERGENCY" if self.is_emergency else ""
        return (
            f"[{self.appointment_id}] {self.date} "
            f"{self.start_time.strftime(fmt)} – {self.end_time.strftime(fmt)} | "
            f"Status: {self._status.value.upper()}{priority_flag}"
        )

    def __lt__(self, other: "Appointment") -> bool:
        """Enable sorting by appointment datetime."""
        return self.appointment_datetime() < other.appointment_datetime()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "appointment_id":      self.appointment_id,
            "patient_id":          self.patient_id,
            "doctor_id":           self.doctor_id,
            "slot_id":             self.slot_id,
            "date":                self.date.isoformat(),
            "start_time":          self.start_time.isoformat(),
            "end_time":            self.end_time.isoformat(),
            "status":              self._status.value,
            "priority":            self.priority.value,
            "notes":               self.notes,
            "booked_at":           self.booked_at.isoformat(),
            "booked_by":           self.booked_by,
            "cancellation_reason": self.cancellation_reason,
            "cancelled_by":        self.cancelled_by,
            "cancelled_at":        self.cancelled_at.isoformat() if self.cancelled_at else None,
            "reschedule_count":    self.reschedule_count,
            "calendar_event_id":   self.calendar_event_id,
            "calendar_event_link": self.calendar_event_link,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Appointment":
        date_value = data["date"]
        start_time_value = data["start_time"]
        end_time_value = data["end_time"]
        booked_at_value = data.get("booked_at")

        a = cls(
            patient_id=data["patient_id"],
            doctor_id=data["doctor_id"],
            slot_id=data["slot_id"],
            date=date.fromisoformat(date_value) if isinstance(date_value, str) else date_value,
            start_time=time.fromisoformat(start_time_value) if isinstance(start_time_value, str) else start_time_value,
            end_time=time.fromisoformat(end_time_value) if isinstance(end_time_value, str) else end_time_value,
            priority=AppointmentPriority(data.get("priority", "normal")),
            notes=data.get("notes"),
            booked_by=data.get("booked_by"),
            appointment_id=data.get("appointment_id"),
            calendar_event_id=data.get("calendar_event_id"),
            calendar_event_link=data.get("calendar_event_link"),
        )
        if booked_at_value:
            a.booked_at = (
                datetime.fromisoformat(booked_at_value)
                if isinstance(booked_at_value, str)
                else booked_at_value
            )
        # Restore mutable state
        a._status           = AppointmentStatus(data.get("status", "booked"))
        a.cancellation_reason = data.get("cancellation_reason")
        a.cancelled_by      = data.get("cancelled_by")
        a.cancelled_at      = (
            datetime.fromisoformat(data["cancelled_at"])
            if data.get("cancelled_at") else None
        )
        a.reschedule_count  = data.get("reschedule_count", 0)
        return a
