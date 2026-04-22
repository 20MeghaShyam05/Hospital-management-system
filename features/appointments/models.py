from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PriorityEnum(str, Enum):
    NORMAL = "normal"
    EMERGENCY = "emergency"


class AppointmentBookRequest(BaseModel):
    patient_id: str
    doctor_id: str
    slot_id: str
    date: date
    notes: Optional[str] = Field(None, max_length=500)
    priority: PriorityEnum = PriorityEnum.NORMAL

    model_config = {"extra": "forbid"}


class AppointmentResponse(BaseModel):
    appointment_id: str
    patient_id: str
    doctor_id: str
    slot_id: str
    date: date
    start_time: time
    end_time: time
    status: str
    priority: str
    notes: Optional[str] = None
    booked_at: Optional[datetime] = None
    booked_by: Optional[str] = None
    cancellation_reason: Optional[str] = None
    cancelled_by: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    reschedule_count: int = 0
    queue_position: Optional[int] = None
    estimated_wait_min: Optional[int] = None
    calendar_event_id: Optional[str] = None
    calendar_event_link: Optional[str] = None

    model_config = {"from_attributes": True}


class CancelRequest(BaseModel):
    reason: str = Field(..., min_length=10, max_length=300)
    cancelled_by: Optional[str] = None

    model_config = {"extra": "forbid"}


class RescheduleRequest(BaseModel):
    new_slot_id: str
    new_date: date

    model_config = {"extra": "forbid"}


class NurseAssignRequest(BaseModel):
    nurse_id: str

    model_config = {"extra": "forbid"}


class NurseAssignResponse(BaseModel):
    appointment_id: str
    patient_id: str
    doctor_id: str
    date: date
    start_time: time
    status: str
    assigned_nurse_id: Optional[str] = None

    model_config = {"from_attributes": True}
