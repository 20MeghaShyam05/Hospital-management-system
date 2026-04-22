from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from features.core.dependencies import ensure_appointment_scope, get_current_user, require_roles
from features.prescriptions.models import PrescriptionCreate, PrescriptionResponse
from features.prescriptions.service import PrescriptionModuleService, get_prescription_module
from features.shared.utils.rbac import Role

router = APIRouter()


@router.post("", response_model=PrescriptionResponse, status_code=201, summary="Create a prescription")
async def create_prescription(
    data: PrescriptionCreate,
    svc: PrescriptionModuleService = Depends(get_prescription_module),
    current_user: dict = Depends(require_roles(Role.DOCTOR)),
):
    apt = svc.get_appointment(data.appointment_id)
    if not apt:
        raise HTTPException(status_code=404, detail=f"Appointment {data.appointment_id} not found")
    ensure_appointment_scope(current_user, apt)
    return svc.create_prescription(
        appointment_id=data.appointment_id,
        diagnosis=data.diagnosis,
        medicines=data.medicines,
        advice=data.advice,
        follow_up_date=data.follow_up_date,
        current_user=current_user,
    )


@router.get("/patient/{patient_id}", response_model=list[PrescriptionResponse], summary="View patient prescriptions")
async def get_patient_prescriptions(
    patient_id: str,
    svc: PrescriptionModuleService = Depends(get_prescription_module),
    current_user: dict = Depends(get_current_user),
):
    role = current_user.get("role")
    if role == Role.PATIENT.value and current_user.get("linked_patient_id") != patient_id:
        raise HTTPException(status_code=403, detail="You can only view your own prescriptions.")
    if role not in {Role.ADMIN.value, Role.DOCTOR.value, Role.PATIENT.value, Role.SYSTEM.value}:
        raise HTTPException(status_code=403, detail="Role is not permitted to view prescriptions.")
    return svc.get_patient_prescriptions(patient_id)


@router.get("/doctor/{doctor_id}", response_model=list[PrescriptionResponse], summary="View doctor prescriptions")
async def get_doctor_prescriptions(
    doctor_id: str,
    svc: PrescriptionModuleService = Depends(get_prescription_module),
    current_user: dict = Depends(require_roles(Role.DOCTOR, Role.ADMIN)),
):
    if current_user.get("role") == Role.DOCTOR.value and current_user.get("linked_doctor_id") != doctor_id:
        raise HTTPException(status_code=403, detail="You can only view your own prescriptions.")
    return svc.get_doctor_prescriptions(doctor_id)
