# =============================================================================
# models/person.py
# Base class shared by Patient and Doctor
# =============================================================================
# Covers: Magic methods (__init__, __repr__), Encapsulation,
#         Regex validation (NF2 + NF3 from NSL spec)
# =============================================================================

from __future__ import annotations

import re
from datetime import datetime


# ---------------------------------------------------------------------------
# Shared regex patterns (NSL spec: NF2 + NF3 for both GO1 and GO2)
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)
_MOBILE_RE = re.compile(
    r"^[6-9]\d{9}$"  # 10-digit Indian mobile, starts with 6-9
)


def validate_email(email: str) -> str:
    """Validate email against RFC-5322-lite pattern from NSL NF2.

    Returns the cleaned email string or raises ValueError.
    """
    cleaned = email.strip().lower()
    if not _EMAIL_RE.match(cleaned):
        raise ValueError(f"Invalid email format: '{email}'")
    return cleaned


def validate_mobile(mobile: str) -> str:
    """Validate mobile against 10-digit Indian pattern from NSL NF3.

    Strips spaces/dashes before checking so '98765-43210' is accepted.
    Returns the bare 10-digit string or raises ValueError.
    """
    digits = re.sub(r"[\s\-\(\)]", "", mobile)
    if not _MOBILE_RE.match(digits):
        raise ValueError(
            f"Mobile must be a valid 10-digit number starting with 6-9. Got: '{mobile}'"
        )
    return digits


class Person:
    """Abstract base for Patient and Doctor.

    Provides:
    - Shared fields: full_name, email, mobile, is_active
    - Shared validation (email + mobile regex)
    - __repr__ and __str__ magic methods
    - created_at timestamp (set on construction)

    Subclasses must call super().__init__() and provide their own
    generate_id() class method to set self.id.
    """

    def __init__(
        self,
        full_name: str,
        email: str,
        mobile: str,
        is_active: bool = True,
    ) -> None:
        # --- R004 / R024: name must be >= 3 chars -------------------------
        name = full_name.strip()
        if len(name) < 3:
            raise ValueError("Please enter a valid full name (min 3 characters).")
        self._full_name: str = name

        # --- NF2: email validation ----------------------------------------
        self._email: str = validate_email(email)

        # --- NF3: mobile validation ----------------------------------------
        self._mobile: str = validate_mobile(mobile)

        self._is_active: bool = is_active
        self.created_at: datetime = datetime.now()

    # ------------------------------------------------------------------
    # Properties — encapsulate private attributes
    # ------------------------------------------------------------------

    @property
    def full_name(self) -> str:
        return self._full_name

    @full_name.setter
    def full_name(self, value: str) -> None:
        name = value.strip()
        if len(name) < 3:
            raise ValueError("Full name must be at least 3 characters.")
        self._full_name = name

    @property
    def email(self) -> str:
        return self._email

    @email.setter
    def email(self, value: str) -> None:
        self._email = validate_email(value)

    @property
    def mobile(self) -> str:
        return self._mobile

    @mobile.setter
    def mobile(self, value: str) -> None:
        self._mobile = validate_mobile(value)

    @property
    def is_active(self) -> bool:
        return self._is_active

    def deactivate(self) -> None:
        """Soft-delete: mark person as inactive (NSL R011 / R030)."""
        self._is_active = False

    def activate(self) -> None:
        self._is_active = True

    # ------------------------------------------------------------------
    # Magic methods
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"full_name={self._full_name!r}, "
            f"email={self._email!r}, "
            f"is_active={self._is_active}"
            f")"
        )

    def __str__(self) -> str:
        status = "active" if self._is_active else "inactive"
        return f"{self._full_name} <{self._email}> [{status}]"

    def __eq__(self, other: object) -> bool:
        """Two Person records are the same if their emails match."""
        if not isinstance(other, Person):
            return NotImplemented
        return self._email == other._email

    def __hash__(self) -> int:
        return hash(self._email)

    # ------------------------------------------------------------------
    # Serialisation helper (used by database layer + API responses)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a JSON-safe dict of base fields.

        Subclasses should call super().to_dict() and merge their own fields.
        """
        return {
            "full_name": self._full_name,
            "email": self._email,
            "mobile": self._mobile,
            "is_active": self._is_active,
            "created_at": self.created_at.isoformat(),
        }
