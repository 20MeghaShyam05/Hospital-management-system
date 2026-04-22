from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from features.core.dependencies import ensure_doctor_scope, require_roles
from features.queue.models import QueueEntryResponse, QueueSummaryResponse
from features.queue.service import QueueModuleService, get_queue_module
from features.shared.utils.rbac import Role

router = APIRouter()


@router.get("/{doctor_id}/{queue_date}", response_model=list[QueueEntryResponse], summary="View daily queue (GO7 LO1)")
async def get_queue(
    doctor_id: str,
    queue_date: date,
    svc: QueueModuleService = Depends(get_queue_module),
    current_user: dict = Depends(require_roles(Role.DOCTOR)),
):
    doctor = svc.get_doctor(doctor_id)
    if not doctor:
        return []
    if current_user.get("role") == Role.DOCTOR.value:
        ensure_doctor_scope(current_user, doctor)
    return svc.get_queue(doctor_id, queue_date)


@router.get("/{doctor_id}/{queue_date}/summary", response_model=QueueSummaryResponse, summary="Queue summary counts")
async def get_queue_summary(
    doctor_id: str,
    queue_date: date,
    svc: QueueModuleService = Depends(get_queue_module),
    current_user: dict = Depends(require_roles(Role.DOCTOR)),
):
    doctor = svc.get_doctor(doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail=f"Doctor {doctor_id} not found")
    if current_user.get("role") == Role.DOCTOR.value:
        ensure_doctor_scope(current_user, doctor)
    return svc.get_queue_summary(doctor_id, queue_date)


@router.post("/{doctor_id}/next", response_model=QueueEntryResponse, summary="Call next patient (GO7 LO2)")
async def call_next_patient(
    doctor_id: str,
    queue_date: date = None,
    svc: QueueModuleService = Depends(get_queue_module),
    current_user: dict = Depends(require_roles(Role.DOCTOR)),
):
    doctor = svc.get_doctor(doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail=f"Doctor {doctor_id} not found")
    if current_user.get("role") == Role.DOCTOR.value:
        ensure_doctor_scope(current_user, doctor)
    entry = svc.call_next_patient(doctor_id, queue_date or date.today())
    if not entry:
        raise HTTPException(status_code=404, detail="No patients waiting in queue")
    return entry


@router.post("/{doctor_id}/{appointment_id}/complete", response_model=QueueEntryResponse, summary="Mark appointment completed (GO7 LO3)")
async def complete_appointment(
    doctor_id: str,
    appointment_id: str,
    svc: QueueModuleService = Depends(get_queue_module),
    current_user: dict = Depends(require_roles(Role.DOCTOR)),
):
    doctor = svc.get_doctor(doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail=f"Doctor {doctor_id} not found")
    if current_user.get("role") == Role.DOCTOR.value:
        ensure_doctor_scope(current_user, doctor)
    return svc.complete_appointment(doctor_id, appointment_id)


@router.post("/{doctor_id}/{appointment_id}/no-show", response_model=QueueEntryResponse, summary="Mark patient as no-show (GO7 LO3)")
async def mark_no_show(
    doctor_id: str,
    appointment_id: str,
    svc: QueueModuleService = Depends(get_queue_module),
    current_user: dict = Depends(require_roles(Role.DOCTOR)),
):
    doctor = svc.get_doctor(doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail=f"Doctor {doctor_id} not found")
    if current_user.get("role") == Role.DOCTOR.value:
        ensure_doctor_scope(current_user, doctor)
    return svc.mark_no_show(doctor_id, appointment_id)
