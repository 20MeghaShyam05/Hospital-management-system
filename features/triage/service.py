from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import Depends

from features.core.dependencies import get_booking_service
from features.shared.services.booking_service import BookingService


class TriageModuleService:
    def __init__(self, booking: BookingService) -> None:
        self._booking = booking

    def create_triage_entry(self, **payload) -> dict:
        return self._booking.create_triage_entry(**payload)

    def get_triage_entries(self, patient_id: str) -> list[dict]:
        return self._booking.get_triage_entries(patient_id)

    def get_triage_for_date(self, triage_date: date, doctor_id: Optional[str] = None) -> list[dict]:
        return self._booking.get_triage_for_date(triage_date, doctor_id)


def get_triage_module(booking: BookingService = Depends(get_booking_service)) -> TriageModuleService:
    return TriageModuleService(booking)
