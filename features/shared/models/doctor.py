# =============================================================================
# models/doctor.py
# Doctor entity — inherits Person
# =============================================================================
# NSL reference: GO2 (Register Doctor) entity definition
# Fields: doctor_id, full_name, email, mobile, specialization,
#         max_patients_per_day, is_active
# Business Rules: R021, R022, R023, R030, R031
# =============================================================================

from __future__ import annotations

from datetime import date, time
from enum import Enum
from typing import Optional
from uuid import uuid4

from config import settings
from features.shared.models.person import Person


# ---------------------------------------------------------------------------
# Specialization enum (NSL spec GO2 enum values)
# ---------------------------------------------------------------------------

class Specialization(str, Enum):
    GENERAL_PHYSICIAN = "General Physician"
    CARDIOLOGIST      = "Cardiologist"
    DERMATOLOGIST     = "Dermatologist"
    NEUROLOGIST       = "Neurologist"
    ORTHOPEDIST       = "Orthopedist"
    PEDIATRICIAN      = "Pediatrician"
    PSYCHIATRIST      = "Psychiatrist"
    GYNECOLOGIST      = "Gynecologist"
    ENT_SPECIALIST    = "ENT Specialist"
    OPHTHALMOLOGIST   = "Ophthalmologist"


def _next_doctor_id() -> str:
    return str(uuid4())


def _next_doctor_uhid() -> str:
    """Generate a hospital-friendly doctor UHID."""
    return f"HMS-DOC-{date.today():%Y%m%d}-{uuid4().hex[:6].upper()}"


# ---------------------------------------------------------------------------
# Doctor class
# ---------------------------------------------------------------------------

class Doctor(Person):
    """Represents a registered hospital doctor.

    Inherits shared validation (email + mobile regex) from Person.
    Adds doctor-specific fields: specialization and daily patient cap.

    Usage
    -----
    >>> d = Doctor(
    ...     full_name="Dr. Priya Nair",
    ...     email="priya.nair@hospital.com",
    ...     mobile="9988776655",
    ...     specialization=Specialization.CARDIOLOGIST,
    ...     max_patients_per_day=20,
    ... )
    >>> len(d.doctor_id)
    36
    """

    def __init__(
        self,
        full_name: str,
        email: str,
        mobile: str,
        specialization: Specialization,
        max_patients_per_day: int = 20,
        work_start_time: Optional[time] = None,
        work_end_time: Optional[time] = None,
        consultation_duration_minutes: Optional[int] = None,
        doctor_id: Optional[str] = None,  # pass in to restore from DB
        uhid: Optional[str] = None,
    ) -> None:
        # Shared validation via Person.__init__
        super().__init__(full_name=full_name, email=email, mobile=mobile)

        self.specialization: Specialization = specialization

        # --- R023: max_patients_per_day >= 1 (E6 mitigation) ---------------
        if max_patients_per_day < 1 or max_patients_per_day > 100:
            raise ValueError(
                "Doctor must accept between 1 and 100 patients per day."
            )
        self.max_patients_per_day: int = max_patients_per_day

        # --- Per-doctor work hours (defaults from specialization config) ---
        spec_hours = settings.SPECIALIZATION_WORK_HOURS.get(
            specialization.value, {"start": "09:00", "end": "17:00"}
        )
        self.work_start_time: time = work_start_time or time.fromisoformat(spec_hours["start"])
        self.work_end_time:   time = work_end_time   or time.fromisoformat(spec_hours["end"])

        # --- Per-specialization consultation duration ----------------------
        default_duration = settings.SPECIALIZATION_CONSULTATION_MINUTES.get(
            specialization.value, settings.DEFAULT_SLOT_DURATION
        )
        self.consultation_duration_minutes: int = consultation_duration_minutes or default_duration

        # ID: use provided (DB restore) or auto-generate
        self.doctor_id: str = doctor_id or _next_doctor_id()
        self.uhid: str = uhid or _next_doctor_uhid()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def generate_uhid() -> str:
        return _next_doctor_uhid()

    def display_name(self) -> str:
        """Formatted name for UI dropdowns."""
        return f"Dr. {self.full_name} ({self.specialization.value})"

    # ------------------------------------------------------------------
    # Magic methods
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Doctor("
            f"doctor_id={self.doctor_id!r}, "
            f"full_name={self.full_name!r}, "
            f"specialization={self.specialization.value!r}, "
            f"is_active={self.is_active}"
            f")"
        )

    def __str__(self) -> str:
        return (
            f"[{self.doctor_id}] Dr. {self.full_name} — "
            f"{self.specialization.value} "
            f"(max {self.max_patients_per_day}/day)"
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "doctor_id": self.doctor_id,
            "uhid": self.uhid,
            "specialization": self.specialization.value,
            "max_patients_per_day": self.max_patients_per_day,
            "work_start_time": self.work_start_time.isoformat(),
            "work_end_time": self.work_end_time.isoformat(),
            "consultation_duration_minutes": self.consultation_duration_minutes,
        })
        return base

    @classmethod
    def from_dict(cls, data: dict) -> "Doctor":
        """Restore a Doctor from a DB/JSON dict (preserves original ID)."""
        work_start_raw = data.get("work_start_time")
        work_end_raw = data.get("work_end_time")

        d = cls(
            full_name=data["full_name"],
            email=data["email"],
            mobile=data["mobile"],
            specialization=Specialization(data["specialization"]),
            max_patients_per_day=data.get("max_patients_per_day", 20),
            work_start_time=(
                time.fromisoformat(work_start_raw)
                if isinstance(work_start_raw, str)
                else work_start_raw
            ),
            work_end_time=(
                time.fromisoformat(work_end_raw)
                if isinstance(work_end_raw, str)
                else work_end_raw
            ),
            consultation_duration_minutes=data.get("consultation_duration_minutes"),
            doctor_id=data.get("doctor_id"),
            uhid=data.get("uhid"),
        )
        if not data.get("is_active", True):
            d.deactivate()
        return d
