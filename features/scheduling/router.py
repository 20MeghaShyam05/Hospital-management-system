from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from features.core.dependencies import ensure_doctor_scope, get_current_user, require_roles
from features.scheduling.models import SlotBlockRequest, SlotResponse
from features.scheduling.service import SchedulingModuleService, get_scheduling_module
from features.shared.utils.rbac import Role

router = APIRouter()


@router.get("/slots/{doctor_id}/{slot_date}", response_model=list[SlotResponse], summary="Get available slots for booking (GO4 LO1 NF1)")
async def get_available_slots(
    doctor_id: str,
    slot_date: date,
    svc: SchedulingModuleService = Depends(get_scheduling_module),
    current_user: dict = Depends(get_current_user),
):
    return svc.get_available_slots(doctor_id, slot_date)


@router.get("/slots/{doctor_id}/{slot_date}/all", response_model=list[SlotResponse], summary="Get all generated slots for display")
async def get_all_slots_for_display(
    doctor_id: str,
    slot_date: date,
    svc: SchedulingModuleService = Depends(get_scheduling_module),
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.DOCTOR)),
):
    doctor = svc.get_doctor(doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail=f"Doctor {doctor_id} not found")
    if current_user.get("role") == Role.DOCTOR.value:
        ensure_doctor_scope(current_user, doctor)
    return svc.get_all_slots_for_display(doctor_id, slot_date)


@router.patch("/slots/{slot_id}", response_model=SlotResponse, summary="Block or unblock a doctor's slot")
async def set_slot_blocked(
    slot_id: str,
    data: SlotBlockRequest,
    svc: SchedulingModuleService = Depends(get_scheduling_module),
    current_user: dict = Depends(require_roles(Role.DOCTOR)),
):
    existing = svc.get_slot(slot_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Slot {slot_id} not found")
    doctor = svc.get_doctor(existing["doctor_id"])
    if not doctor:
        raise HTTPException(status_code=404, detail=f"Doctor {existing['doctor_id']} not found")
    ensure_doctor_scope(current_user, doctor)
    slot = svc.set_slot_blocked(slot_id, data.is_blocked)
    doctor = svc.get_doctor(slot["doctor_id"])
    if not doctor:
        raise HTTPException(status_code=404, detail=f"Doctor {slot['doctor_id']} not found")
    return slot
