from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import Depends

from features.core.dependencies import get_booking_service
from features.shared.services.booking_service import BookingService


class AppointmentModuleService:
    def __init__(self, booking: BookingService) -> None:
        self._booking = booking

    def get_patient(self, patient_id: str) -> dict | None:
        return self._booking.get_patient(patient_id)

    def get_doctor(self, doctor_id: str) -> dict | None:
        return self._booking.get_doctor(doctor_id)

    def book_appointment(self, **payload) -> dict:
        return self._booking.book_appointment(**payload)

    def get_appointment(self, appointment_id: str) -> dict | None:
        return self._booking.get_appointment(appointment_id)

    def get_patient_appointments(self, patient_id: str) -> list[dict]:
        return self._booking.get_patient_appointments(patient_id)

    def get_doctor_appointments(
        self,
        doctor_id: str,
        for_date: date,
        status_filter: Optional[list[str]] = None,
    ) -> list[dict]:
        return self._booking.get_doctor_appointments(doctor_id, for_date, status_filter)

    def get_all_appointments(
        self,
        for_date: date | None = None,
        doctor_id: str | None = None,
        status_filter: Optional[list[str]] = None,
    ) -> list[dict]:
        return self._booking.get_all_appointments(for_date, doctor_id, status_filter)

    def cancel_appointment(self, **payload) -> dict:
        return self._booking.cancel_appointment(**payload)

    def reschedule_appointment(self, **payload) -> dict:
        return self._booking.reschedule_appointment(**payload)

    def assign_nurse(self, appointment_id: str, nurse_id: str) -> dict | None:
        return self._booking._db.assign_nurse_to_appointment(appointment_id, nurse_id)

    def get_appointments_for_date(self, date_str: str) -> list[dict]:
        return self._booking._db.get_appointments_for_date(date_str, status_filter=["booked"])


def get_appointment_module(booking: BookingService = Depends(get_booking_service)) -> AppointmentModuleService:
    return AppointmentModuleService(booking)
