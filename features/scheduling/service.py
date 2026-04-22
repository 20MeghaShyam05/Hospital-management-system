from __future__ import annotations

from datetime import date

from fastapi import Depends

from features.core.dependencies import get_booking_service
from features.shared.services.booking_service import BookingService


class SchedulingModuleService:
    def __init__(self, booking: BookingService) -> None:
        self._booking = booking

    def get_doctor(self, doctor_id: str) -> dict | None:
        return self._booking.get_doctor(doctor_id)

    def get_available_slots(self, doctor_id: str, for_date: date) -> list[dict]:
        return self._booking.get_available_slots(doctor_id, for_date)

    def get_all_slots_for_display(self, doctor_id: str, for_date: date) -> list[dict]:
        return self._booking.get_all_slots_for_display(doctor_id, for_date)

    def get_slot(self, slot_id: str) -> dict | None:
        return self._booking.get_slot(slot_id)

    def set_slot_blocked(self, slot_id: str, is_blocked: bool) -> dict:
        return self._booking.set_slot_blocked(slot_id, is_blocked)


def get_scheduling_module(booking: BookingService = Depends(get_booking_service)) -> SchedulingModuleService:
    return SchedulingModuleService(booking)
