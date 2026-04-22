# =============================================================================
# models/nurse.py
# Nurse entity — inherits Person
# =============================================================================
# Nurses enter patient vitals and assign patients to the appropriate
# queue (normal or emergency) before they see the doctor.
# =============================================================================

from __future__ import annotations

from datetime import date
from typing import Optional
from uuid import uuid4

from features.shared.models.person import Person


def _next_nurse_id() -> str:
    return str(uuid4())


def _next_nurse_uhid() -> str:
    """Generate a hospital-friendly nurse UHID."""
    return f"HMS-NRS-{date.today():%Y%m%d}-{uuid4().hex[:6].upper()}"


class Nurse(Person):
    """Represents a registered hospital nurse.

    Inherits shared validation (email + mobile regex) from Person.
    Nurses are responsible for recording patient vitals and triaging
    patients into normal or emergency queues.

    Usage
    -----
    >>> n = Nurse(
    ...     full_name="Anjali Kumar",
    ...     email="anjali.kumar@hospital.com",
    ...     mobile="9876543210",
    ... )
    >>> len(n.nurse_id)
    36
    """

    def __init__(
        self,
        full_name: str,
        email: str,
        mobile: str,
        nurse_id: Optional[str] = None,
        uhid: Optional[str] = None,
    ) -> None:
        super().__init__(full_name=full_name, email=email, mobile=mobile)

        self.nurse_id: str = nurse_id or _next_nurse_id()
        self.uhid: str = uhid or _next_nurse_uhid()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def generate_uhid() -> str:
        return _next_nurse_uhid()

    def display_name(self) -> str:
        """Formatted name for UI dropdowns."""
        return f"Nurse {self.full_name}"

    # ------------------------------------------------------------------
    # Magic methods
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Nurse("
            f"nurse_id={self.nurse_id!r}, "
            f"full_name={self.full_name!r}, "
            f"is_active={self.is_active}"
            f")"
        )

    def __str__(self) -> str:
        return f"[{self.nurse_id}] Nurse {self.full_name} <{self.email}>"

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        base = super().to_dict()
        base.update({
            "nurse_id": self.nurse_id,
            "uhid": self.uhid,
        })
        return base

    @classmethod
    def from_dict(cls, data: dict) -> "Nurse":
        """Restore a Nurse from a DB/JSON dict (preserves original ID)."""
        n = cls(
            full_name=data["full_name"],
            email=data["email"],
            mobile=data["mobile"],
            nurse_id=data.get("nurse_id"),
            uhid=data.get("uhid"),
        )
        if not data.get("is_active", True):
            n.deactivate()
        return n
