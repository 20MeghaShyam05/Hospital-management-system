from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from features.appointments.models import (
    AppointmentBookRequest,
    AppointmentResponse,
    CancelRequest,
    NurseAssignRequest,
    NurseAssignResponse,
    RescheduleRequest,
)
from features.appointments.service import AppointmentModuleService, get_appointment_module
from features.core.dependencies import (
    ensure_appointment_scope,
    ensure_doctor_scope,
    ensure_patient_scope,
    get_current_user,
    require_roles,
)
from features.shared.utils.rbac import Role

router = APIRouter()


@router.post("", response_model=AppointmentResponse, status_code=201, summary="Book an appointment (GO4 LO2)")
async def book_appointment(
    data: AppointmentBookRequest,
    svc: AppointmentModuleService = Depends(get_appointment_module),
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.PATIENT, Role.FRONT_DESK, Role.NURSE)),
):
    if current_user.get("role") == Role.PATIENT.value:
        patient = svc.get_patient(data.patient_id)
        if not patient:
            raise HTTPException(status_code=404, detail=f"Patient {data.patient_id} not found")
        ensure_patient_scope(current_user, patient)
    return svc.book_appointment(
        patient_id=data.patient_id,
        doctor_id=data.doctor_id,
        slot_id=data.slot_id,
        appointment_date=data.date,
        notes=data.notes,
        priority=data.priority.value,
        current_user=current_user,
    )


@router.get("", response_model=list[AppointmentResponse], summary="List appointments with optional filters")
async def list_appointments(
    date_filter: date | None = None,
    doctor_id: str | None = None,
    svc: AppointmentModuleService = Depends(get_appointment_module),
    current_user: dict = Depends(get_current_user),
):
    role = current_user.get("role")
    if role == Role.DOCTOR.value:
        doctor_id = current_user.get("linked_doctor_id")
    elif role == Role.PATIENT.value:
        return svc.get_patient_appointments(current_user.get("linked_patient_id"))
    return svc.get_all_appointments(date_filter, doctor_id)


@router.get("/{appointment_id}", response_model=AppointmentResponse, summary="Get appointment details")
async def get_appointment(
    appointment_id: str,
    svc: AppointmentModuleService = Depends(get_appointment_module),
    current_user: dict = Depends(get_current_user),
):
    apt = svc.get_appointment(appointment_id)
    if not apt:
        raise HTTPException(status_code=404, detail=f"Appointment {appointment_id} not found")
    ensure_appointment_scope(current_user, apt)
    return apt


@router.get("/patient/{patient_id}", response_model=list[AppointmentResponse], summary="Get all appointments for a patient")
async def get_patient_appointments(
    patient_id: str,
    svc: AppointmentModuleService = Depends(get_appointment_module),
    current_user: dict = Depends(get_current_user),
):
    patient = svc.get_patient(patient_id)
    if not patient:
        return []
    ensure_patient_scope(current_user, patient)
    return svc.get_patient_appointments(patient_id)


@router.get("/doctor/{doctor_id}/{appt_date}", response_model=list[AppointmentResponse], summary="Get doctor's appointments for a date")
async def get_doctor_appointments(
    doctor_id: str,
    appt_date: date,
    svc: AppointmentModuleService = Depends(get_appointment_module),
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.DOCTOR)),
):
    doctor = svc.get_doctor(doctor_id)
    if not doctor:
        return []
    if current_user.get("role") == Role.DOCTOR.value:
        ensure_doctor_scope(current_user, doctor)
    return svc.get_doctor_appointments(doctor_id, appt_date)


@router.post("/{appointment_id}/cancel", response_model=AppointmentResponse, summary="Cancel an appointment (GO5 LO1)")
async def cancel_appointment(
    appointment_id: str,
    data: CancelRequest,
    svc: AppointmentModuleService = Depends(get_appointment_module),
    current_user: dict = Depends(require_roles(Role.PATIENT)),
):
    apt = svc.get_appointment(appointment_id)
    if not apt:
        raise HTTPException(status_code=404, detail=f"Appointment {appointment_id} not found")
    ensure_appointment_scope(current_user, apt)
    return svc.cancel_appointment(
        appointment_id=appointment_id,
        reason=data.reason,
        cancelled_by=data.cancelled_by,
        current_user=current_user,
    )


@router.post("/{appointment_id}/reschedule", response_model=AppointmentResponse, summary="Reschedule an appointment (GO6 LO3)")
async def reschedule_appointment(
    appointment_id: str,
    data: RescheduleRequest,
    svc: AppointmentModuleService = Depends(get_appointment_module),
    current_user: dict = Depends(require_roles(Role.PATIENT)),
):
    apt = svc.get_appointment(appointment_id)
    if not apt:
        raise HTTPException(status_code=404, detail=f"Appointment {appointment_id} not found")
    ensure_appointment_scope(current_user, apt)
    return svc.reschedule_appointment(
        appointment_id=appointment_id,
        new_slot_id=data.new_slot_id,
        new_date=data.new_date,
        current_user=current_user,
    )


@router.post("/{appointment_id}/assign-nurse", response_model=NurseAssignResponse, summary="Assign a nurse to an appointment")
async def assign_nurse(
    appointment_id: str,
    data: NurseAssignRequest,
    svc: AppointmentModuleService = Depends(get_appointment_module),
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.FRONT_DESK)),
):
    apt = svc.get_appointment(appointment_id)
    if not apt:
        raise HTTPException(status_code=404, detail=f"Appointment {appointment_id} not found")
    updated = svc.assign_nurse(appointment_id, data.nurse_id)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to assign nurse")
    return updated


@router.post("/{appointment_id}/reassign-nurse", response_model=NurseAssignResponse, summary="Reassign appointment to a different nurse")
async def reassign_nurse(
    appointment_id: str,
    data: NurseAssignRequest,
    svc: AppointmentModuleService = Depends(get_appointment_module),
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.FRONT_DESK, Role.NURSE)),
):
    apt = svc.get_appointment(appointment_id)
    if not apt:
        raise HTTPException(status_code=404, detail=f"Appointment {appointment_id} not found")
    updated = svc.assign_nurse(appointment_id, data.nurse_id)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to reassign nurse")
    return updated


@router.get("/nurse-assignments/{assignment_date}", response_model=list[NurseAssignResponse], summary="Get all appointments for a date with nurse assignments")
async def get_nurse_assignments(
    assignment_date: date,
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.FRONT_DESK, Role.NURSE)),
    svc: AppointmentModuleService = Depends(get_appointment_module),
):
    return svc.get_appointments_for_date(assignment_date.isoformat())
