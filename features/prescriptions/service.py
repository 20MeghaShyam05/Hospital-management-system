from __future__ import annotations

from fastapi import Depends

from features.core.dependencies import get_booking_service
from features.shared.services.booking_service import BookingService


class PrescriptionModuleService:
    def __init__(self, booking: BookingService) -> None:
        self._booking = booking

    def create_prescription(self, **payload) -> dict:
        return self._booking.create_prescription(**payload)

    def get_patient_prescriptions(self, patient_id: str) -> list[dict]:
        return self._booking.get_patient_prescriptions(patient_id)

    def get_doctor_prescriptions(self, doctor_id: str) -> list[dict]:
        return self._booking.get_doctor_prescriptions(doctor_id)

    def get_appointment(self, appointment_id: str) -> dict | None:
        return self._booking.get_appointment(appointment_id)


def get_prescription_module(
    booking: BookingService = Depends(get_booking_service),
) -> PrescriptionModuleService:
    return PrescriptionModuleService(booking)
