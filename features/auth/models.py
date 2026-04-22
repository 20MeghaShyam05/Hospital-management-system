from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    identifier: str
    password: str = Field(..., min_length=4, max_length=100)
    role: str

    model_config = {"extra": "forbid"}


class UserSessionResponse(BaseModel):
    user_id: str
    role: str
    display_name: str
    linked_patient_id: Optional[str] = None
    linked_patient_uhid: Optional[str] = None
    linked_doctor_id: Optional[str] = None
    linked_doctor_uhid: Optional[str] = None
    linked_nurse_id: Optional[str] = None
    linked_nurse_uhid: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserSessionResponse


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=4, max_length=100)
    new_password: str = Field(..., min_length=8, max_length=100)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if len(value.strip()) < 8:
            raise ValueError("New password must be at least 8 characters long.")
        return value

    model_config = {"extra": "forbid"}
