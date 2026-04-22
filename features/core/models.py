from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str


class HealthResponse(BaseModel):
    status: str = "ok"
    postgres: bool
    mongo: bool
