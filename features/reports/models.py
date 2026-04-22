from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel


class ReportResponse(BaseModel):
    date: date
    doctor_id_filter: Optional[str] = None
    total_appointments: int = 0
    total_completed: int = 0
    total_cancelled: int = 0
    total_no_shows: int = 0
    busiest_doctor_id: Optional[str] = None
    busiest_doctor_name: Optional[str] = None
    busiest_doctor_specialization: Optional[str] = None
    peak_hour: Optional[int] = None
    peak_hour_label: Optional[str] = None
    slot_utilization_pct: float = 0.0
    cancellation_rate_pct: float = 0.0

    model_config = {"from_attributes": True}
