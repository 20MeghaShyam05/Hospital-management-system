# =============================================================================
# models/patient.py
# Patient entity — inherits Person
# =============================================================================
# NSL reference: GO1 (Register Patient) entity definition
# Fields: patient_id, full_name, email, mobile, date_of_birth, gender,
#         blood_group, address, registration_date, registered_by, is_active
# Business Rules: R001, R002, R003, R004, R010, R011, R012
# =============================================================================

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional
from uuid import uuid4

from features.shared.models.person import Person


# ---------------------------------------------------------------------------
# Enums (NSL spec enum values for Patient fields)
# ---------------------------------------------------------------------------

class Gender(str, Enum):
    MALE   = "Male"
    FEMALE = "Female"
    OTHER  = "Other"


class BloodGroup(str, Enum):
    A_POS  = "A+"
    A_NEG  = "A-"
    B_POS  = "B+"
    B_NEG  = "B-"
    O_POS  = "O+"
    O_NEG  = "O-"
    AB_POS = "AB+"
    AB_NEG = "AB-"


def _next_patient_id() -> str:
    return str(uuid4())


def _next_uhid() -> str:
    """Generate a hospital-friendly UHID for patient records."""
    return f"HMS-PAT-{date.today():%Y%m%d}-{uuid4().hex[:6].upper()}"


# ---------------------------------------------------------------------------
# Patient class
# ---------------------------------------------------------------------------

class Patient(Person):
    """Represents a registered hospital patient.

    Inherits shared validation (email + mobile regex) from Person.
    Adds patient-specific fields, DOB validation, and visit tracking.

    Usage
    -----
    >>> p = Patient(
    ...     full_name="Riya Sharma",
    ...     email="riya@example.com",
    ...     mobile="9876543210",
    ...     date_of_birth=date(1995, 6, 15),
    ...     gender=Gender.FEMALE,
    ... )
    >>> len(p.patient_id)
    36
    """

    def __init__(
        self,
        full_name: str,
        email: str,
        mobile: str,
        date_of_birth: Optional[date] = None,
        gender: Optional[Gender] = None,
        blood_group: Optional[BloodGroup] = None,
        address: Optional[str] = None,
        registered_by: Optional[str] = None,
        patient_id: Optional[str] = None,       # pass in to restore from DB
        uhid: Optional[str] = None,
    ) -> None:
        # Shared validation via Person.__init__
        super().__init__(full_name=full_name, email=email, mobile=mobile)

        # --- R003: DOB must be in the past ---------------------------------
        if date_of_birth is not None:
            if date_of_birth >= date.today():
                raise ValueError("Date of birth cannot be a future date.")
        self.date_of_birth: Optional[date] = date_of_birth

        # --- Address max 300 chars (NSL spec) ------------------------------
        if address and len(address) > 300:
            raise ValueError("Address must not exceed 300 characters.")

        self.gender: Optional[Gender] = gender
        self.blood_group: Optional[BloodGroup] = blood_group
        self.address: Optional[str] = address
        self.registration_date: date = date.today()
        self.registered_by: Optional[str] = registered_by

        # Single UUID identifier used throughout the application + database
        self.patient_id: str = patient_id or _next_patient_id()
        self.uhid: str = uhid or _next_uhid()

        # Visit tracking (incremented by BookingService on each booking)
        self.visit_count: int = 0
        self.visit_type: str = "first_visit"

    # ------------------------------------------------------------------
    # Visit tracking helpers (called by BookingService)
    # ------------------------------------------------------------------

    def record_visit(self) -> None:
        """Increment visit count and update visit_type."""
        self.visit_count += 1
        if self.visit_count > 1:
            self.visit_type = "returning_patient"

    @staticmethod
    def generate_uhid() -> str:
        return _next_uhid()

    # ------------------------------------------------------------------
    # Age helper (derived — not stored)
    # ------------------------------------------------------------------

    @property
    def age(self) -> Optional[int]:
        if self.date_of_birth is None:
            return None
        today = date.today()
        years = today.year - self.date_of_birth.year
        # Adjust if birthday hasn't occurred yet this year
        if (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day):
            years -= 1
        return years

    # ------------------------------------------------------------------
    # Magic methods (override Person's __repr__)
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Patient("
            f"patient_id={self.patient_id!r}, "
            f"full_name={self.full_name!r}, "
            f"email={self.email!r}, "
            f"is_active={self.is_active}"
            f")"
        )

    def __str__(self) -> str:
        age_str = f", age {self.age}" if self.age is not None else ""
        return f"[{self.patient_id}] {self.full_name}{age_str} <{self.email}>"

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "patient_id": self.patient_id,
            "uhid": self.uhid,
            "date_of_birth": self.date_of_birth.isoformat() if self.date_of_birth else None,
            "gender": self.gender.value if self.gender else None,
            "blood_group": self.blood_group.value if self.blood_group else None,
            "address": self.address,
            "registration_date": self.registration_date.isoformat(),
            "registered_by": self.registered_by,
            "visit_count": self.visit_count,
            "visit_type": self.visit_type,
        })
        return base

    @classmethod
    def from_dict(cls, data: dict) -> "Patient":
        """Restore a Patient from a DB/JSON dict (preserves original IDs)."""
        dob = None
        if data.get("date_of_birth"):
            dob = date.fromisoformat(data["date_of_birth"])
        gender = Gender(data["gender"]) if data.get("gender") else None
        bg = BloodGroup(data["blood_group"]) if data.get("blood_group") else None

        p = cls(
            full_name=data["full_name"],
            email=data["email"],
            mobile=data["mobile"],
            date_of_birth=dob,
            gender=gender,
            blood_group=bg,
            address=data.get("address"),
            registered_by=data.get("registered_by"),
            patient_id=data.get("patient_id"),
            uhid=data.get("uhid"),
        )
        p.visit_count = data.get("visit_count", 0)
        p.visit_type  = data.get("visit_type", "first_visit")
        if not data.get("is_active", True):
            p.deactivate()
        return p
