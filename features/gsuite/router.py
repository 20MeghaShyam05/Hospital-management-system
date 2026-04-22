# =============================================================================
# features/gsuite/router.py
# FastAPI endpoints for G-Suite operations
# =============================================================================
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from typing import Optional

logger = logging.getLogger(__name__)

from features.core.dependencies import require_roles, get_booking_service
from features.shared.utils.rbac import Role
from features.gsuite.models import (
    FormSyncResponse, FormSyncStats, EmailRequest, EmailResponse,
    DriveFileResponse, CalendarEventRequest, CalendarEventResponse,
    CalendarListItem, PatientDriveSaveRequest,
)

router = APIRouter()


# =========================================================================
# FORMS SYNC
# =========================================================================

@router.post("/forms/sync", response_model=FormSyncResponse, summary="Trigger Google Forms sync")
async def trigger_forms_sync(
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.NURSE, Role.FRONT_DESK)),
):
    """Manually trigger a sync of Google Form responses → patient database."""
    from features.core.dependencies import app_state
    from features.gsuite.forms_sync import sync_form_responses

    result = sync_form_responses(app_state.booking)
    return result


@router.get("/forms/stats", response_model=FormSyncStats, summary="Get forms sync stats")
async def get_forms_stats(
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.NURSE, Role.FRONT_DESK)),
):
    """Get current sync statistics."""
    from features.gsuite.forms_sync import get_sync_stats
    return get_sync_stats()


# =========================================================================
# GMAIL
# =========================================================================

@router.post("/email/send", response_model=EmailResponse, summary="Send email via Gmail")
async def send_email(
    req: EmailRequest,
    current_user: dict = Depends(require_roles(Role.ADMIN)),
):
    """Send an ad-hoc email via the Gmail API."""
    from features.gsuite.gmail_service import get_gmail

    gmail = get_gmail()
    if not gmail.is_available:
        raise HTTPException(status_code=503, detail="Gmail service unavailable")

    result = gmail.send_email(req.to, req.subject, req.body_html)
    if result:
        return EmailResponse(success=True, message_id=result.get("id"))
    return EmailResponse(success=False, error="Failed to send email")


# =========================================================================
# DRIVE
# =========================================================================

@router.post("/drive/upload", response_model=DriveFileResponse, summary="Upload file to Drive")
async def upload_to_drive(
    file: UploadFile = File(...),
    patient_id: Optional[str] = Form(None),
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.DOCTOR, Role.NURSE)),
):
    """Upload a document to the MediFlow Google Drive folder."""
    from features.gsuite.drive_service import get_drive

    drive = get_drive()
    if not drive.is_available:
        raise HTTPException(status_code=503, detail="Drive service unavailable")

    content = await file.read()
    result = drive.upload_file(
        file_content=content,
        filename=file.filename or "document",
        mime_type=file.content_type or "application/octet-stream",
        subfolder=patient_id,
    )
    if not result:
        raise HTTPException(status_code=500, detail="Upload failed")
    return result


@router.get("/drive/files", response_model=list[DriveFileResponse], summary="List Drive files")
async def list_drive_files(
    patient_id: Optional[str] = None,
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.DOCTOR, Role.NURSE)),
):
    """List files in the MediFlow Drive folder, optionally filtered by patient."""
    from features.gsuite.drive_service import get_drive

    drive = get_drive()
    if not drive.is_available:
        raise HTTPException(status_code=503, detail="Drive service unavailable")

    files = drive.list_files(patient_id=patient_id)
    return files


# =========================================================================
# CALENDAR
# =========================================================================

@router.post("/calendar/event", response_model=CalendarEventResponse, summary="Create calendar event")
async def create_calendar_event(
    req: CalendarEventRequest,
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.DOCTOR)),
):
    """Create a Google Calendar event for an appointment."""
    from features.gsuite.calendar_service import get_calendar

    cal = get_calendar()
    if not cal.is_available:
        raise HTTPException(status_code=503, detail="Calendar service unavailable")

    result = cal.create_appointment_event(
        doctor_name=req.doctor_name,
        patient_name=req.patient_name,
        appointment_date=req.appointment_date,
        start_time=req.start_time,
        duration_minutes=req.duration_minutes,
        patient_email=req.patient_email,
        doctor_email=req.doctor_email,
        appointment_id=req.appointment_id,
    )
    if not result:
        raise HTTPException(status_code=500, detail="Event creation failed")
    return result


@router.delete("/calendar/event/{event_id}", summary="Cancel calendar event")
async def cancel_calendar_event(
    event_id: str,
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.DOCTOR)),
):
    """Cancel (delete) a Google Calendar event."""
    from features.gsuite.calendar_service import get_calendar

    cal = get_calendar()
    if not cal.is_available:
        raise HTTPException(status_code=503, detail="Calendar service unavailable")

    success = cal.cancel_event(event_id)
    if not success:
        raise HTTPException(status_code=500, detail="Event cancellation failed")
    return {"detail": "Event cancelled"}


@router.get("/calendar/upcoming", response_model=list[CalendarListItem], summary="Upcoming events")
async def list_upcoming_events(
    current_user: dict = Depends(require_roles(Role.ADMIN, Role.DOCTOR)),
):
    """List upcoming calendar events."""
    from features.gsuite.calendar_service import get_calendar

    cal = get_calendar()
    if not cal.is_available:
        raise HTTPException(status_code=503, detail="Calendar service unavailable")

    return cal.list_upcoming_events()


# =========================================================================
# PATIENT SAVE-TO-DRIVE (prescription / triage → PDF → Google Drive)
# =========================================================================

@router.get("/drive/ping")
async def ping():
    return {"status": "ok"}

@router.post("/drive/patient-save", response_model=DriveFileResponse, summary="Save patient record to Drive as PDF")
async def patient_save_to_drive(
    req: PatientDriveSaveRequest,
    current_user: dict = Depends(require_roles(Role.PATIENT)),
    booking=Depends(get_booking_service)
):
    import traceback
    from fastapi.responses import JSONResponse
    try:
        from features.gsuite.drive_service import get_drive
        from features.gsuite.pdf_generator import generate_prescription_pdf, generate_triage_pdf

        patient_id = current_user.get("linked_patient_id")
        if not patient_id:
            raise HTTPException(status_code=403, detail="No linked patient profile found.")

        drive = get_drive()
        if not drive.is_available:
            raise HTTPException(status_code=503, detail="Google Drive service unavailable")

        if req.record_type == "prescription":
            prescriptions = booking.get_patient_prescriptions(patient_id)
            record = next((rx for rx in prescriptions if rx.get("prescription_id") == req.record_id), None)
            if not record:
                raise HTTPException(status_code=404, detail="Prescription not found or does not belong to you.")
            pdf_bytes = generate_prescription_pdf(record)
            filename = f"Prescription_{req.record_id}_{record.get('created_at', '')[:10]}.pdf"

        elif req.record_type == "triage":
            triage_entries = booking.get_triage_entries(patient_id)
            record = next((t for t in triage_entries if t.get("triage_id") == req.record_id), None)
            if not record:
                raise HTTPException(status_code=404, detail="Triage record not found or does not belong to you.")
            pdf_bytes = generate_triage_pdf(record)
            filename = f"Triage_{req.record_id}_{record.get('date', '')}.pdf"

        else:
            raise HTTPException(status_code=400, detail="Invalid record_type.")

        result = drive.upload_file(
            file_content=pdf_bytes,
            filename=filename,
            mime_type="application/pdf",
            subfolder=patient_id,
        )
        if not result:
            raise HTTPException(status_code=500, detail="Failed to upload PDF to Google Drive.")

        # Share the uploaded file with the patient's email so it appears in
        # "Shared with me" inside their own Google Drive account.
        try:
            patient = booking.get_patient(patient_id)
            patient_email = patient.get("email") if patient else None
            if patient_email:
                drive.share_file(result["id"], patient_email)
        except Exception as share_exc:
            logger.warning(f"Could not share Drive file with patient: {share_exc}")

        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "traceback": traceback.format_exc()})
