from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class QueueEntryResponse(BaseModel):
    queue_id: str
    doctor_id: str
    date: date
    patient_id: str
    appointment_id: str
    queue_position: int
    is_emergency: bool
    status: str
    added_at: datetime | None = None

    model_config = {"from_attributes": True}


class QueueSummaryResponse(BaseModel):
    total: int
    emergency: int
    waiting: int
    in_progress: int
