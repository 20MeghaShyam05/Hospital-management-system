# =============================================================================
# features/gsuite/calendar_service.py
# Create / update / delete Google Calendar events for appointments
# Per-doctor calendars — each doctor gets events on the authenticated calendar
# =============================================================================
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from config import settings
from features.gsuite.auth import build_service

logger = logging.getLogger(__name__)


class CalendarService:
    """Manage Google Calendar events for doctor appointments."""

    def __init__(self, calendar_id: Optional[str] = None):
        self._service = build_service("calendar", "v3")
        self._calendar_id = calendar_id or settings.GOOGLE_CALENDAR_ID
        if not self._service:
            logger.warning("Google Calendar service unavailable")

    @property
    def is_available(self) -> bool:
        return self._service is not None

    def create_appointment_event(
        self,
        doctor_name: str,
        patient_name: str,
        appointment_date: str,
        start_time: str,
        duration_minutes: int = 15,
        patient_email: Optional[str] = None,
        doctor_email: Optional[str] = None,
        appointment_id: str = "",
    ) -> Optional[dict]:
        """Create a calendar event for an appointment.

        Args:
            doctor_name: Doctor's display name.
            patient_name: Patient's display name.
            appointment_date: Date string (YYYY-MM-DD).
            start_time: Time string (HH:MM).
            duration_minutes: Appointment duration.
            patient_email: Patient's email (for attendee invite).
            doctor_email: Doctor's email (for attendee invite).
            appointment_id: Reference ID.

        Returns dict with {event_id, link} or None on failure.
        """
        if not self.is_available:
            logger.warning("Calendar unavailable — skipping event creation")
            return None

        try:
            start_dt = datetime.fromisoformat(f"{appointment_date}T{start_time}")
            end_dt = start_dt + timedelta(minutes=duration_minutes)

            attendees = []
            if patient_email:
                attendees.append({"email": patient_email})
            if doctor_email:
                attendees.append({"email": doctor_email})

            event = {
                "summary": f"Appointment: {patient_name} → Dr. {doctor_name}",
                "description": (
                    f"Appointment ID: {appointment_id}\n"
                    f"Patient: {patient_name}\n"
                    f"Doctor: Dr. {doctor_name}\n\n"
                    "Auto-created by MediFlow HMS"
                ),
                "start": {
                    "dateTime": start_dt.isoformat(),
                    "timeZone": "Asia/Kolkata",
                },
                "end": {
                    "dateTime": end_dt.isoformat(),
                    "timeZone": "Asia/Kolkata",
                },
                "attendees": attendees,
                "reminders": {
                    "useDefault": False,
                    "overrides": [
                        {"method": "email", "minutes": 60},
                        {"method": "popup", "minutes": 15},
                    ],
                },
                "colorId": "9",  # Blueberry
            }

            result = self._service.events().insert(
                calendarId=self._calendar_id, body=event, sendUpdates="all"
            ).execute()

            logger.info(f"Calendar event created: {result['id']} for {appointment_id}")
            return {"event_id": result["id"], "link": result.get("htmlLink", "")}

        except Exception as exc:
            logger.error(f"Calendar event creation failed: {exc}")
            return None

    def cancel_event(self, event_id: str) -> bool:
        """Delete a calendar event by its event ID."""
        if not self.is_available:
            return False
        try:
            self._service.events().delete(
                calendarId=self._calendar_id, eventId=event_id,
                sendUpdates="all",
            ).execute()
            logger.info(f"Calendar event cancelled: {event_id}")
            return True
        except Exception as exc:
            logger.error(f"Calendar event cancel failed ({event_id}): {exc}")
            return False

    def update_event_time(
        self, event_id: str, new_date: str, new_time: str, duration_minutes: int = 15
    ) -> Optional[dict]:
        """Reschedule a calendar event to a new date/time."""
        if not self.is_available:
            return None
        try:
            start_dt = datetime.fromisoformat(f"{new_date}T{new_time}")
            end_dt = start_dt + timedelta(minutes=duration_minutes)

            event = self._service.events().get(
                calendarId=self._calendar_id, eventId=event_id
            ).execute()

            event["start"] = {"dateTime": start_dt.isoformat(), "timeZone": "Asia/Kolkata"}
            event["end"] = {"dateTime": end_dt.isoformat(), "timeZone": "Asia/Kolkata"}

            result = self._service.events().update(
                calendarId=self._calendar_id, eventId=event_id,
                body=event, sendUpdates="all",
            ).execute()

            logger.info(f"Calendar event rescheduled: {event_id} → {new_date} {new_time}")
            return {"event_id": result["id"], "link": result.get("htmlLink", "")}
        except Exception as exc:
            logger.error(f"Calendar event update failed ({event_id}): {exc}")
            return None

    def list_upcoming_events(self, max_results: int = 20) -> list[dict]:
        """List upcoming events from the calendar."""
        if not self.is_available:
            return []
        try:
            now = datetime.utcnow().isoformat() + "Z"
            result = self._service.events().list(
                calendarId=self._calendar_id,
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            events = result.get("items", [])
            return [
                {
                    "event_id": e["id"],
                    "summary": e.get("summary", ""),
                    "start": e.get("start", {}).get("dateTime", e.get("start", {}).get("date", "")),
                    "end": e.get("end", {}).get("dateTime", ""),
                    "link": e.get("htmlLink", ""),
                    "attendees": [a.get("email", "") for a in e.get("attendees", [])],
                }
                for e in events
            ]
        except Exception as exc:
            logger.error(f"Calendar list failed: {exc}")
            return []


# Module-level singleton (lazy)
_calendar: Optional[CalendarService] = None


def get_calendar() -> CalendarService:
    """Get or create the Calendar service singleton."""
    global _calendar
    if _calendar is None:
        _calendar = CalendarService()
    return _calendar
