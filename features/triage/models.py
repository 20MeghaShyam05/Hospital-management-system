from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class QueueTypeEnum(str, Enum):
    NORMAL = "normal"
    EMERGENCY = "emergency"


class TriageCreate(BaseModel):
    patient_id: str
    nurse_id: str
    doctor_id: str
    date: date
    queue_type: QueueTypeEnum = QueueTypeEnum.NORMAL
    appointment_id: Optional[str] = None
    blood_pressure: Optional[str] = Field(None, max_length=20, description="e.g. 120/80")
    heart_rate: Optional[int] = Field(None, ge=20, le=300, description="Beats per minute")
    temperature: Optional[float] = Field(None, ge=30.0, le=45.0, description="Celsius")
    weight: Optional[float] = Field(None, ge=0.5, le=500.0, description="Kilograms")
    oxygen_saturation: Optional[float] = Field(None, ge=0, le=100, description="SpO2 %")
    symptoms: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=500)

    model_config = {"extra": "forbid"}


class TriageResponse(BaseModel):
    triage_id: str
    patient_id: str
    nurse_id: str
    doctor_id: str
    appointment_id: Optional[str] = None
    date: date
    blood_pressure: Optional[str] = None
    heart_rate: Optional[int] = None
    temperature: Optional[float] = None
    weight: Optional[float] = None
    oxygen_saturation: Optional[float] = None
    symptoms: Optional[str] = None
    queue_type: str
    notes: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
