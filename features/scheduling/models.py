from __future__ import annotations

from datetime import date, time

from pydantic import BaseModel, Field
from typing import Optional


class SlotResponse(BaseModel):
    slot_id: str
    doctor_id: str
    date: date
    start_time: time
    end_time: time
    is_lunch_break: bool
    is_booked: bool
    is_blocked: bool
    label: Optional[str] = None

    model_config = {"from_attributes": True}


class SlotBlockRequest(BaseModel):
    is_blocked: bool = Field(..., description="True blocks the slot; false reopens it.")

    model_config = {"extra": "forbid"}
