from __future__ import annotations

from fastapi import Depends

from features.core.dependencies import get_booking_service
from features.shared.services.booking_service import BookingService


class DoctorModuleService:
    def __init__(self, booking: BookingService) -> None:
        self._booking = booking

    def register_doctor(self, **payload) -> dict:
        return self._booking.register_doctor(**payload)

    def list_doctors(self, active_only: bool = True) -> list[dict]:
        return self._booking.list_doctors(active_only=active_only)

    def get_doctor(self, doctor_id: str) -> dict | None:
        return self._booking.get_doctor(doctor_id)


def get_doctor_module(booking: BookingService = Depends(get_booking_service)) -> DoctorModuleService:
    return DoctorModuleService(booking)
