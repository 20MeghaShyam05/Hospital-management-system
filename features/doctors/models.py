from __future__ import annotations

from datetime import time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SpecializationEnum(str, Enum):
    GENERAL_PHYSICIAN = "General Physician"
    CARDIOLOGIST = "Cardiologist"
    DERMATOLOGIST = "Dermatologist"
    NEUROLOGIST = "Neurologist"
    ORTHOPEDIST = "Orthopedist"
    PEDIATRICIAN = "Pediatrician"
    PSYCHIATRIST = "Psychiatrist"
    GYNECOLOGIST = "Gynecologist"
    ENT_SPECIALIST = "ENT Specialist"
    OPHTHALMOLOGIST = "Ophthalmologist"


class DoctorCreate(BaseModel):
    full_name: str = Field(..., min_length=3, max_length=100)
    email: str = Field(..., description="Valid email address")
    mobile: str = Field(..., min_length=10, max_length=10)
    specialization: SpecializationEnum
    max_patients_per_day: int = Field(20, ge=1, le=100)
    work_start_time: Optional[time] = None
    work_end_time: Optional[time] = None
    consultation_duration_minutes: Optional[int] = None

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, value: str) -> str:
        import re

        if not re.match(r"^[6-9]\d{9}$", value):
            raise ValueError("Mobile must be a valid 10-digit number starting with 6-9")
        return value

    @field_validator("consultation_duration_minutes")
    @classmethod
    def validate_consultation_duration(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value not in (10, 15, 20, 30):
            raise ValueError("Consultation duration must be one of 10, 15, 20, 30 minutes")
        return value

    model_config = {"extra": "forbid"}


class DoctorResponse(BaseModel):
    doctor_id: str
    uhid: str
    full_name: str
    email: str
    mobile: str
    specialization: str
    max_patients_per_day: int
    work_start_time: Optional[time] = None
    work_end_time: Optional[time] = None
    consultation_duration_minutes: Optional[int] = None
    is_active: bool = True

    model_config = {"from_attributes": True}
