from __future__ import annotations

from datetime import date

from fastapi import Depends

from features.core.dependencies import get_booking_service
from features.shared.services.booking_service import BookingService


class QueueModuleService:
    def __init__(self, booking: BookingService) -> None:
        self._booking = booking

    def get_doctor(self, doctor_id: str) -> dict | None:
        return self._booking.get_doctor(doctor_id)

    def get_queue(self, doctor_id: str, for_date: date) -> list[dict]:
        return self._booking.get_queue(doctor_id, for_date)

    def get_queue_summary(self, doctor_id: str, for_date: date) -> dict:
        return self._booking.get_queue_summary(doctor_id, for_date)

    def call_next_patient(self, doctor_id: str, for_date: date) -> dict | None:
        return self._booking.call_next_patient(doctor_id, for_date)

    def complete_appointment(self, doctor_id: str, appointment_id: str) -> dict:
        return self._booking.complete_appointment(doctor_id, appointment_id)

    def mark_no_show(self, doctor_id: str, appointment_id: str) -> dict:
        return self._booking.mark_no_show(doctor_id, appointment_id)


def get_queue_module(booking: BookingService = Depends(get_booking_service)) -> QueueModuleService:
    return QueueModuleService(booking)
