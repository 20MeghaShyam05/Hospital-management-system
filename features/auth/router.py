from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from features.auth.models import ChangePasswordRequest, LoginRequest, LoginResponse, UserSessionResponse
from features.auth.service import AuthModuleService, get_auth_module
from features.core.rate_limiter import limiter
from features.core.dependencies import get_current_user

router = APIRouter()


@router.post("/login", response_model=LoginResponse, summary="Login with role-specific credentials")
@limiter.limit("5/minute")
async def login(
    request: Request,
    data: LoginRequest,
    svc: AuthModuleService = Depends(get_auth_module),
):
    result = svc.login(data.identifier, data.password, data.role)
    return {
        "access_token": result["access_token"],
        "token_type": "bearer",
        "user": result["user"],
    }


@router.get("/me", response_model=UserSessionResponse, summary="Get current authenticated user")
async def me(current_user: dict = Depends(get_current_user)):
    return current_user


@router.post("/change-password", summary="Change the current user's password")
async def change_password(
    data: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    svc: AuthModuleService = Depends(get_auth_module),
):
    svc.change_password(current_user, data.current_password, data.new_password)
    return {"detail": "Password updated successfully."}
