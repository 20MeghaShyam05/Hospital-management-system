from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from features.core.dependencies import ensure_doctor_scope, get_current_user, require_roles
from features.doctors.models import DoctorCreate, DoctorResponse
from features.doctors.service import DoctorModuleService, get_doctor_module
from features.shared.utils.rbac import Role

router = APIRouter()


@router.post("", response_model=DoctorResponse, status_code=201, summary="Register a new doctor (GO2 LO1)")
async def register_doctor(
    data: DoctorCreate,
    svc: DoctorModuleService = Depends(get_doctor_module),
    current_user: dict = Depends(require_roles(Role.ADMIN)),
):
    return svc.register_doctor(
        full_name=data.full_name,
        email=data.email,
        mobile=data.mobile,
        specialization=data.specialization.value,
        max_patients_per_day=data.max_patients_per_day,
        work_start_time=data.work_start_time,
        work_end_time=data.work_end_time,
        consultation_duration_minutes=data.consultation_duration_minutes,
        current_user=current_user,
    )


@router.get("", response_model=list[DoctorResponse], summary="List all doctors")
async def list_doctors(
    active_only: bool = True,
    svc: DoctorModuleService = Depends(get_doctor_module),
    current_user: dict = Depends(get_current_user),
):
    return svc.list_doctors(active_only=active_only)


@router.get("/{doctor_id}", response_model=DoctorResponse, summary="Get doctor by ID")
async def get_doctor(
    doctor_id: str,
    svc: DoctorModuleService = Depends(get_doctor_module),
    current_user: dict = Depends(get_current_user),
):
    doctor = svc.get_doctor(doctor_id)
    if not doctor:
        raise HTTPException(status_code=404, detail=f"Doctor {doctor_id} not found")
    if current_user.get("role") == Role.DOCTOR.value:
        ensure_doctor_scope(current_user, doctor)
    return doctor
