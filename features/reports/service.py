from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import Depends

from features.core.dependencies import get_booking_service
from features.shared.services.booking_service import BookingService


class ReportModuleService:
    def __init__(self, booking: BookingService) -> None:
        self._booking = booking

    def get_doctor(self, doctor_id: str) -> dict | None:
        return self._booking.get_doctor(doctor_id)

    def get_report_data(self, report_date: date, doctor_id: Optional[str] = None) -> dict:
        return self._booking.get_report_data(report_date, doctor_id=doctor_id)


def get_report_module(booking: BookingService = Depends(get_booking_service)) -> ReportModuleService:
    return ReportModuleService(booking)
