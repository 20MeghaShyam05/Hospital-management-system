from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from features.core.dependencies import require_roles
from features.nurses.models import NurseCreate, NurseResponse
from features.nurses.service import NurseModuleService, get_nurse_module
from features.shared.utils.rbac import Role

router = APIRouter()


@router.post("", response_model=NurseResponse, status_code=201, summary="Register a new nurse")
async def register_nurse(
    data: NurseCreate,
    svc: NurseModuleService = Depends(get_nurse_module),
    current_user: dict = Depends(require_roles(Role.ADMIN)),
):
    return svc.register_nurse(
        full_name=data.full_name,
        email=data.email,
        mobile=data.mobile,
        current_user=current_user,
    )


@router.get("", response_model=list[NurseResponse], summary="List all nurses")
async def list_nurses(
    active_only: bool = True,
    svc: NurseModuleService = Depends(get_nurse_module),
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.DOCTOR, Role.NURSE, Role.FRONT_DESK)),
):
    return svc.list_nurses(active_only=active_only)


@router.get("/{nurse_id}", response_model=NurseResponse, summary="Get nurse by ID")
async def get_nurse(
    nurse_id: str,
    svc: NurseModuleService = Depends(get_nurse_module),
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.DOCTOR, Role.NURSE, Role.FRONT_DESK)),
):
    nurse = svc.get_nurse(nurse_id)
    if not nurse:
        raise HTTPException(status_code=404, detail=f"Nurse {nurse_id} not found")
    return nurse
