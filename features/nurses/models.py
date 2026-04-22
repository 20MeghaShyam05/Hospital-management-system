from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class NurseCreate(BaseModel):
    full_name: str = Field(..., min_length=3, max_length=100)
    email: str = Field(..., description="Valid email address")
    mobile: str = Field(..., min_length=10, max_length=10)

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, value: str) -> str:
        import re
        if not re.match(r"^[6-9]\d{9}$", value):
            raise ValueError("Mobile must be a valid 10-digit number starting with 6-9")
        return value

    model_config = {"extra": "forbid"}


class NurseResponse(BaseModel):
    nurse_id: str
    uhid: str
    full_name: str
    email: str
    mobile: str
    is_active: bool = True

    model_config = {"from_attributes": True}
