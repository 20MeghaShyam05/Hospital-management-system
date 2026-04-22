from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class PrescriptionCreate(BaseModel):
    appointment_id: str
    diagnosis: str = Field(..., min_length=2, max_length=1000)
    medicines: str = Field(..., min_length=2, max_length=2000)
    advice: Optional[str] = Field(None, max_length=2000)
    follow_up_date: Optional[date] = None

    model_config = {"extra": "forbid"}


class PrescriptionResponse(BaseModel):
    prescription_id: str
    appointment_id: str
    patient_id: str
    doctor_id: str
    doctor_specialization: Optional[str] = None
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    diagnosis: str
    medicines: str
    advice: Optional[str] = None
    follow_up_date: Optional[date] = None
    created_by: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
