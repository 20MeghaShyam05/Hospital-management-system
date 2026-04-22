from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from features.core.dependencies import ensure_patient_scope, get_current_user, require_roles
from features.patients.models import PatientCreate, PatientResponse
from features.patients.service import PatientModuleService, get_patient_module
from features.shared.utils.rbac import Role

router = APIRouter()


@router.post("", response_model=PatientResponse, status_code=201, summary="Register a new patient (GO1 LO1)")
async def register_patient(
    data: PatientCreate,
    svc: PatientModuleService = Depends(get_patient_module),
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.PATIENT, Role.NURSE, Role.FRONT_DESK)),
):
    return svc.register_patient(
        full_name=data.full_name,
        email=data.email,
        mobile=data.mobile,
        date_of_birth=data.date_of_birth,
        gender=data.gender.value if data.gender else None,
        blood_group=data.blood_group.value if data.blood_group else None,
        address=data.address,
        registered_by=data.registered_by,
        current_user=current_user,
    )


@router.get("", response_model=list[PatientResponse], summary="List all patients")
async def list_patients(
    active_only: bool = True,
    svc: PatientModuleService = Depends(get_patient_module),
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.NURSE, Role.FRONT_DESK)),
):
    return svc.list_patients(active_only=active_only)


@router.get("/{patient_id}", response_model=PatientResponse, summary="Get patient by ID")
async def get_patient(
    patient_id: str,
    svc: PatientModuleService = Depends(get_patient_module),
    current_user: dict = Depends(get_current_user),
):
    patient = svc.get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail=f"Patient {patient_id} not found")
    ensure_patient_scope(current_user, patient)
    return patient
