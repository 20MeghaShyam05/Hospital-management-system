# =============================================================================
# models/queue.py
# AppointmentQueue entity + TriageGroup enum
# =============================================================================
# NSL reference: GO7 (Manage Appointment Queue) entity definition
# Fields: queue_id, doctor_id, date, patient_id, appointment_id,
#         queue_position, is_emergency, status, added_at
# Business Rules: R130, R131, R132
#
# Design note
# -----------
# This model represents ONE patient's entry in the queue — a single row.
# QueueManager (services/) owns the full collection and handles:
#   - Priority ordering (emergency first, R130)
#   - Position recalculation (R131)
#   - Status transitions (R132)
# This class just holds the data and enforces its own state transitions.
# =============================================================================

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import uuid4


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class QueueStatus(str, Enum):
    WAITING     = "waiting"
    IN_PROGRESS = "in-progress"
    COMPLETED   = "completed"
    NO_SHOW     = "no-show"
    CANCELLED   = "cancelled"

    @classmethod
    def allowed_transitions(cls) -> dict["QueueStatus", set["QueueStatus"]]:
        """R132 — valid state machine transitions."""
        return {
            cls.WAITING:     {cls.IN_PROGRESS, cls.CANCELLED},
            cls.IN_PROGRESS: {cls.COMPLETED, cls.NO_SHOW},
            cls.COMPLETED:   set(),   # terminal
            cls.NO_SHOW:     set(),   # terminal
            cls.CANCELLED:   set(),   # terminal
        }


class TriageGroup(str, Enum):
    """Classification used by QueueManager's priority queue (DSA layer).

    EMERGENCY entries are always served before NORMAL entries regardless
    of booking time — NSL R130.
    """
    EMERGENCY = "emergency"
    NORMAL    = "normal"


def _next_queue_id() -> str:
    return str(uuid4())


# ---------------------------------------------------------------------------
# AppointmentQueue — one patient's queue entry for a doctor on a date
# ---------------------------------------------------------------------------

class AppointmentQueue:
    """Single queue entry for one patient with one doctor on one date.

    Priority rules (R130)
    ----------------------
    - is_emergency = True  → TriageGroup.EMERGENCY → served first
    - is_emergency = False → TriageGroup.NORMAL    → served in order

    QueueManager builds a heap using (triage_priority, queue_position)
    so emergency entries bubble to the top automatically.

    Status machine (R132)
    ----------------------
    waiting → in-progress → completed
                           → no-show
    waiting → cancelled

    Usage
    -----
    >>> entry = AppointmentQueue(
    ...     doctor_id="doctor-uuid",
    ...     date=date(2026, 3, 27),
    ...     patient_id="patient-uuid",
    ...     appointment_id="appointment-uuid",
    ...     queue_position=1,
    ...     is_emergency=False,
    ... )
    >>> entry.triage_group
    <TriageGroup.NORMAL: 'normal'>
    """

    def __init__(
        self,
        doctor_id: str,
        date: date,
        patient_id: str,
        appointment_id: str,
        queue_position: int,
        is_emergency: bool = False,
        queue_id: Optional[str] = None,
    ) -> None:
        if queue_position < 1:
            raise ValueError("Queue position must be >= 1.")

        self.doctor_id:      str  = doctor_id
        self.date:           date = date
        self.patient_id:     str  = patient_id
        self.appointment_id: str  = appointment_id
        self.queue_position: int  = queue_position
        self.is_emergency:   bool = is_emergency
        self.added_at:   datetime = datetime.now()

        self._status: QueueStatus = QueueStatus.WAITING

        self.queue_id: str = queue_id or _next_queue_id()

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def triage_group(self) -> TriageGroup:
        return TriageGroup.EMERGENCY if self.is_emergency else TriageGroup.NORMAL

    @property
    def triage_priority(self) -> int:
        """Numeric priority for heap comparisons.

        Lower number = higher priority (min-heap convention).
        Emergency → 0, Normal → 1
        """
        return 0 if self.is_emergency else 1

    @property
    def status(self) -> QueueStatus:
        return self._status

    # ------------------------------------------------------------------
    # Status transitions (R132)
    # ------------------------------------------------------------------

    def _validate_transition(self, new_status: QueueStatus) -> None:
        allowed = QueueStatus.allowed_transitions().get(self._status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Invalid queue status transition: "
                f"'{self._status.value}' → '{new_status.value}'"
            )

    def start(self) -> None:
        """Move entry to IN_PROGRESS (doctor calls patient in)."""
        self._validate_transition(QueueStatus.IN_PROGRESS)
        self._status = QueueStatus.IN_PROGRESS

    def complete(self) -> None:
        """Mark consultation as completed."""
        self._validate_transition(QueueStatus.COMPLETED)
        self._status = QueueStatus.COMPLETED

    def mark_no_show(self) -> None:
        """Patient did not show up."""
        self._validate_transition(QueueStatus.NO_SHOW)
        self._status = QueueStatus.NO_SHOW

    def cancel(self) -> None:
        """Remove from queue on appointment cancellation."""
        self._validate_transition(QueueStatus.CANCELLED)
        self._status = QueueStatus.CANCELLED

    # ------------------------------------------------------------------
    # Heap comparison (used by QueueManager's heapq)
    # QueueManager pushes (triage_priority, queue_position, entry) tuples
    # so __lt__ on the tuple handles ordering without needing it here,
    # but we add it for safety in case entries are compared directly.
    # ------------------------------------------------------------------

    def __lt__(self, other: "AppointmentQueue") -> bool:
        """Emergency before normal; then earlier position wins."""
        if self.triage_priority != other.triage_priority:
            return self.triage_priority < other.triage_priority
        return self.queue_position < other.queue_position

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AppointmentQueue):
            return NotImplemented
        return self.queue_id == other.queue_id

    def __hash__(self) -> int:
        return hash(self.queue_id)

    # ------------------------------------------------------------------
    # Magic methods
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"AppointmentQueue("
            f"queue_id={self.queue_id!r}, "
            f"position={self.queue_position}, "
            f"triage={self.triage_group.value!r}, "
            f"status={self._status.value!r}"
            f")"
        )

    def __str__(self) -> str:
        emergency_flag = " 🚨" if self.is_emergency else ""
        return (
            f"[Q{self.queue_position:02d}]{emergency_flag} "
            f"Patient {self.patient_id} | "
            f"Appt {self.appointment_id} | "
            f"Status: {self._status.value.upper()}"
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "queue_id":       self.queue_id,
            "doctor_id":      self.doctor_id,
            "date":           self.date.isoformat(),
            "patient_id":     self.patient_id,
            "appointment_id": self.appointment_id,
            "queue_position": self.queue_position,
            "is_emergency":   self.is_emergency,
            "status":         self._status.value,
            "added_at":       self.added_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AppointmentQueue":
        entry = cls(
            doctor_id=data["doctor_id"],
            date=date.fromisoformat(data["date"]),
            patient_id=data["patient_id"],
            appointment_id=data["appointment_id"],
            queue_position=data["queue_position"],
            is_emergency=data.get("is_emergency", False),
            queue_id=data.get("queue_id"),
        )
        entry._status = QueueStatus(data.get("status", "waiting"))
        return entry
