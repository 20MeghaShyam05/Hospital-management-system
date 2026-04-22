from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class GenderEnum(str, Enum):
    MALE = "Male"
    FEMALE = "Female"
    OTHER = "Other"


class BloodGroupEnum(str, Enum):
    A_POS = "A+"
    A_NEG = "A-"
    B_POS = "B+"
    B_NEG = "B-"
    O_POS = "O+"
    O_NEG = "O-"
    AB_POS = "AB+"
    AB_NEG = "AB-"


class PatientCreate(BaseModel):
    full_name: str = Field(..., min_length=3, max_length=100)
    email: str = Field(..., description="Valid email address")
    mobile: str = Field(..., min_length=10, max_length=10)
    date_of_birth: Optional[date] = None
    gender: Optional[GenderEnum] = None
    blood_group: Optional[BloodGroupEnum] = None
    address: Optional[str] = Field(None, max_length=300)
    registered_by: Optional[str] = None

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, value: str) -> str:
        import re

        if not re.match(r"^[6-9]\d{9}$", value):
            raise ValueError("Mobile must be a valid 10-digit number starting with 6-9")
        return value

    model_config = {"extra": "forbid"}


class PatientResponse(BaseModel):
    patient_id: str
    uhid: str
    full_name: str
    email: str
    mobile: str
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    blood_group: Optional[str] = None
    address: Optional[str] = None
    registration_date: Optional[date] = None
    registered_by: Optional[str] = None
    is_active: bool = True
    visit_count: Optional[int] = 0
    visit_type: Optional[str] = "first_visit"

    model_config = {"from_attributes": True}
