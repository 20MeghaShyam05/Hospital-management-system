from __future__ import annotations

from fastapi import Depends

from features.core.dependencies import get_booking_service
from features.shared.services.booking_service import BookingService


class NurseModuleService:
    def __init__(self, booking: BookingService) -> None:
        self._booking = booking

    def register_nurse(self, **payload) -> dict:
        return self._booking.register_nurse(**payload)

    def list_nurses(self, active_only: bool = True) -> list[dict]:
        return self._booking.list_nurses(active_only=active_only)

    def get_nurse(self, nurse_id: str) -> dict | None:
        return self._booking.get_nurse(nurse_id)


def get_nurse_module(booking: BookingService = Depends(get_booking_service)) -> NurseModuleService:
    return NurseModuleService(booking)
