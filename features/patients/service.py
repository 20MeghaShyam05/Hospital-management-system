from __future__ import annotations

from fastapi import Depends

from features.core.dependencies import get_booking_service
from features.shared.services.booking_service import BookingService


class PatientModuleService:
    def __init__(self, booking: BookingService) -> None:
        self._booking = booking

    def register_patient(self, **payload) -> dict:
        return self._booking.register_patient(**payload)

    def list_patients(self, active_only: bool = True) -> list[dict]:
        return self._booking.list_patients(active_only=active_only)

    def get_patient(self, patient_id: str) -> dict | None:
        return self._booking.get_patient(patient_id)


def get_patient_module(booking: BookingService = Depends(get_booking_service)) -> PatientModuleService:
    return PatientModuleService(booking)
