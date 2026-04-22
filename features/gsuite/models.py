# =============================================================================
# features/gsuite/models.py
# Pydantic models for G-Suite API endpoints
# =============================================================================
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel


class FormSyncResponse(BaseModel):
    new: int
    skipped: int
    errors: list[str]
    appointments_booked: int = 0
    appointments_failed: int = 0


class FormSyncStats(BaseModel):
    last_sync: Optional[str] = None
    total_new: int = 0
    total_skipped: int = 0
    total_errors: int = 0
    total_appointments_booked: int = 0
    total_appointments_failed: int = 0
    last_result: Optional[FormSyncResponse] = None


class EmailRequest(BaseModel):
    to: str
    subject: str
    body_html: str


class EmailResponse(BaseModel):
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None


class DriveFileResponse(BaseModel):
    id: str
    name: str
    webViewLink: Optional[str] = None
    mimeType: Optional[str] = None
    createdTime: Optional[str] = None
    size: Optional[str] = None


class CalendarEventRequest(BaseModel):
    doctor_name: str
    patient_name: str
    appointment_date: str
    start_time: str
    duration_minutes: int = 15
    patient_email: Optional[str] = None
    doctor_email: Optional[str] = None
    appointment_id: str = ""


class CalendarEventResponse(BaseModel):
    event_id: str
    link: str = ""


class CalendarListItem(BaseModel):
    event_id: str
    summary: str = ""
    start: str = ""
    end: str = ""
    link: str = ""
    attendees: list[str] = []


class PatientDriveSaveRequest(BaseModel):
    """Request to save a patient record (prescription or triage) as PDF to Drive."""
    record_type: Literal["prescription", "triage"]
    record_id: str

