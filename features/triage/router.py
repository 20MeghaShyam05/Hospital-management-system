from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from features.core.dependencies import get_current_user, require_roles
from features.triage.models import TriageCreate, TriageResponse
from features.triage.service import TriageModuleService, get_triage_module
from features.shared.utils.rbac import Role

router = APIRouter()


@router.post("", response_model=TriageResponse, status_code=201, summary="Record patient triage vitals")
async def create_triage(
    data: TriageCreate,
    svc: TriageModuleService = Depends(get_triage_module),
    current_user: dict = Depends(require_roles(Role.NURSE)),
):
    return svc.create_triage_entry(
        patient_id=data.patient_id,
        nurse_id=data.nurse_id,
        doctor_id=data.doctor_id,
        triage_date=data.date,
        queue_type=data.queue_type.value,
        appointment_id=data.appointment_id,
        blood_pressure=data.blood_pressure,
        heart_rate=data.heart_rate,
        temperature=data.temperature,
        weight=data.weight,
        oxygen_saturation=data.oxygen_saturation,
        symptoms=data.symptoms,
        notes=data.notes,
        current_user=current_user,
    )


@router.get("/patient/{patient_id}", response_model=list[TriageResponse], summary="Get triage history for patient")
async def get_patient_triage(
    patient_id: str,
    svc: TriageModuleService = Depends(get_triage_module),
    current_user: dict = Depends(get_current_user),
):
    role = current_user.get("role")
    if role == Role.PATIENT.value and current_user.get("linked_patient_id") != patient_id:
        raise HTTPException(status_code=403, detail="You can only view your own triage history.")
    if role not in {Role.NURSE.value, Role.DOCTOR.value, Role.PATIENT.value, Role.SYSTEM.value}:
        raise HTTPException(status_code=403, detail="Role is not permitted to view triage history.")
    return svc.get_triage_entries(patient_id)


@router.get("/date/{triage_date}", response_model=list[TriageResponse], summary="Get triage entries for a date")
async def get_triage_by_date(
    triage_date: date,
    doctor_id: str = None,
    svc: TriageModuleService = Depends(get_triage_module),
    current_user: dict = Depends(require_roles(Role.NURSE, Role.DOCTOR)),
):
    return svc.get_triage_for_date(triage_date, doctor_id)
