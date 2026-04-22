# =============================================================================
# features/gsuite/forms_sync.py
# Poll Google Sheets (linked to a Google Form) for new patient registrations
# and auto-register + book appointments.
# =============================================================================
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, time as dtime
from typing import Any, Optional

from config import settings
from features.gsuite.auth import build_service

logger = logging.getLogger(__name__)

_last_synced_row: int = 0
_sync_lock = threading.Lock()
_sync_stats: dict[str, Any] = {
    "last_sync": None,
    "total_new": 0,
    "total_skipped": 0,
    "total_errors": 0,
    "total_appointments_booked": 0,
    "total_appointments_failed": 0,
    "last_result": None,
}

# Time bands for slot filtering
_TIME_BANDS: dict[str, tuple[dtime, dtime]] = {
    "morning":   (dtime(8, 0),  dtime(12, 0)),
    "afternoon": (dtime(12, 0), dtime(17, 0)),
    "evening":   (dtime(17, 0), dtime(20, 0)),
}


def _parse_form_date(value: str | None, *, field_label: str = "date") -> date | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    for parser in (
        lambda v: date.fromisoformat(v),
        lambda v: datetime.fromisoformat(v).date(),
        lambda v: datetime.strptime(v, "%m/%d/%Y").date(),
        lambda v: datetime.strptime(v, "%d/%m/%Y").date(),
        lambda v: datetime.strptime(v, "%m/%d/%y").date(),
        lambda v: datetime.strptime(v, "%d/%m/%y").date(),
    ):
        try:
            return parser(raw)
        except ValueError:
            continue
    raise ValueError(f"Invalid {field_label} format: {raw}")


def _form_value(data: dict[str, str], *keys: str) -> str:
    for key in keys:
        normalized = key.strip().lower().replace(" ", "_")
        value = data.get(normalized)
        if value:
            return value.strip()
    return ""


def _parse_time_band(raw: str) -> str | None:
    """Normalise 'Morning (8AM-12PM)' → 'morning', etc.

    Also handles shorthand: 'am'/'am slot' → 'morning',
    'pm'/'afternoon' → 'afternoon', 'eve'/'evening' → 'evening'.
    Returns None if unparseable (booking will use first available slot).
    """
    if not raw:
        return None
    lower = raw.strip().lower()
    for band in _TIME_BANDS:
        if band in lower:
            return band
    # Shorthand aliases
    if lower in ("am", "am slot", "forenoon", "fore noon"):
        return "morning"
    if lower in ("pm", "pm slot", "noon", "mid day", "midday"):
        return "afternoon"
    if lower in ("eve", "eve slot", "late", "evening slot"):
        return "evening"
    logger.warning(f"Unrecognised time band value: {raw!r} — will use first available slot")
    return None


def _slot_in_band(slot: dict, band: str) -> bool:
    """Return True if the slot's start_time falls within the given time band."""
    band_start, band_end = _TIME_BANDS[band]
    raw = slot.get("start_time", "")
    try:
        if isinstance(raw, str):
            start = dtime.fromisoformat(raw)
        else:
            start = raw
        return band_start <= start < band_end
    except Exception:
        return False


def _find_and_book_appointment(
    booking_service,
    patient_id: str,
    specialization: str,
    preferred_doctor_name: str,
    appointment_date: date,
    time_band: str | None,
    reason: str,
) -> dict | None:
    """Find the first available slot matching criteria and book it.

    time_band is optional — if None, picks the first available slot of the day.
    Returns the booked appointment dict on success, raises on failure.
    """
    doctors = booking_service.list_doctors(active_only=True)
    logger.info(
        f"Form booking attempt: patient={patient_id} spec={specialization!r} "
        f"doctor={preferred_doctor_name!r} date={appointment_date} band={time_band!r}"
    )

    # Filter by specialization (case-insensitive substring)
    spec_lower = specialization.strip().lower()
    if spec_lower and spec_lower != "any":
        doctors = [
            d for d in doctors
            if spec_lower in d.get("specialization", "").lower()
        ]

    # Further filter by preferred doctor name if supplied
    if preferred_doctor_name:
        name_lower = preferred_doctor_name.strip().lower()
        preferred = [d for d in doctors if name_lower in d.get("full_name", "").lower()]
        if preferred:
            doctors = preferred

    if not doctors:
        raise ValueError(
            f"No active doctors found for specialization '{specialization}'"
            + (f" matching name '{preferred_doctor_name}'" if preferred_doctor_name else "")
        )

    logger.info(f"Form booking: {len(doctors)} candidate doctor(s) after filtering")

    # Walk doctors in order — book on the first slot found
    for doctor in doctors:
        doctor_id = doctor["doctor_id"]
        try:
            slots = booking_service.get_available_slots(doctor_id, appointment_date)
        except Exception as e:
            logger.warning(f"Could not fetch slots for doctor {doctor_id}: {e}")
            continue

        logger.info(f"Form booking: doctor={doctor_id} has {len(slots)} available slot(s) on {appointment_date}")

        # Apply time-band filter if we have one, else use all available slots
        candidate_slots = [s for s in slots if _slot_in_band(s, time_band)] if time_band else slots
        if not candidate_slots:
            logger.info(f"Form booking: no slots in band '{time_band}' for doctor {doctor_id}")
            continue

        slot = candidate_slots[0]
        try:
            appointment = booking_service.book_appointment(
                patient_id=patient_id,
                doctor_id=doctor_id,
                slot_id=slot["slot_id"],
                appointment_date=appointment_date,
                notes=reason or "Booked via Google Form",
                priority="normal",
                booked_by="google_form",
            )
            logger.info(
                f"Form booking SUCCESS: patient={patient_id} doctor={doctor_id} "
                f"slot={slot['slot_id']} date={appointment_date} time={slot.get('start_time')}"
            )
            return appointment
        except Exception as e:
            logger.warning(f"Booking attempt failed for doctor {doctor_id}: {e}")
            continue

    raise ValueError(
        f"No available slots found on {appointment_date} "
        f"for specialization '{specialization}'"
        + (f" in {time_band} band" if time_band else "")
    )


def get_sync_stats() -> dict[str, Any]:
    with _sync_lock:
        return dict(_sync_stats)


def sync_form_responses(booking_service) -> dict[str, Any]:
    """Poll the linked Google Sheet and register any new patients,
    then attempt to book appointments from the form data.

    Google Form columns (A–L):
      Timestamp | Full Name | Email Address | Mobile Number | Date of Birth |
      Gender | Address | Specialization | Preferred Doctor Name |
      Appointment Date | Preferred Time Slot | Reason for Visit
    """
    global _last_synced_row

    spreadsheet_id = settings.GOOGLE_FORMS_SPREADSHEET_ID
    if not spreadsheet_id:
        return {"new": 0, "skipped": 0, "errors": ["GOOGLE_FORMS_SPREADSHEET_ID not configured"]}

    service = build_service("sheets", "v4", use_service_account=True)
    if not service:
        return {"new": 0, "skipped": 0, "errors": ["Google Sheets service unavailable"]}

    sheet_name = settings.GOOGLE_FORMS_SHEET_NAME
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=f"'{sheet_name}'!A:L",
        ).execute()
    except Exception as exc:
        logger.error(f"Failed to read Google Sheet: {exc}")
        return {"new": 0, "skipped": 0, "errors": [str(exc)]}

    rows = result.get("values", [])
    if len(rows) < 2:
        return {"new": 0, "skipped": 0, "errors": []}

    headers = [h.strip().lower().replace(" ", "_") for h in rows[0]]
    stats: dict[str, Any] = {
        "new": 0,
        "skipped": 0,
        "errors": [],
        "appointments_booked": 0,
        "appointments_failed": 0,
    }

    start_idx = max(1, _last_synced_row)
    new_rows = rows[start_idx:]

    for i, row in enumerate(new_rows, start=start_idx):
        try:
            padded = row + [""] * (len(headers) - len(row))
            data = dict(zip(headers, padded))

            # ---- Patient registration fields --------------------------------
            full_name = _form_value(data, "full_name", "full name", "name")
            email     = _form_value(data, "email_address", "email")
            mobile    = _form_value(data, "mobile_number", "mobile", "phone")
            dob       = _form_value(data, "date_of_birth", "dob") or None
            gender    = _form_value(data, "gender") or None
            address   = _form_value(data, "address") or None

            if not email or not full_name:
                stats["errors"].append(f"Row {i+1}: missing name or email")
                continue

            patient = booking_service.register_patient(
                full_name=full_name,
                email=email,
                mobile=mobile,
                date_of_birth=_parse_form_date(dob, field_label="date of birth"),
                gender=gender,
                address=address,
                registered_by="google_form",
            )

            if patient.get("_was_existing"):
                stats["skipped"] += 1
            else:
                stats["new"] += 1
                logger.info(f"Form sync: registered {full_name} ({email})")

            # ---- Appointment booking fields ---------------------------------
            specialization       = _form_value(data, "specialization")
            preferred_doctor     = _form_value(data, "preferred_doctor_name", "preferred_doctor", "doctor_name")
            raw_apt_date         = _form_value(data, "appointment_date", "preferred_date")
            raw_time_band        = _form_value(data, "preferred_time_slot", "preferred_time", "time_slot")
            reason               = _form_value(data, "reason_for_visit", "reason", "chief_complaint")

            apt_date  = _parse_form_date(raw_apt_date, field_label="appointment date")
            time_band = _parse_time_band(raw_time_band)

            logger.info(
                f"Form row {i+1}: spec={specialization!r} apt_date={apt_date} "
                f"time_band={time_band!r} raw_time={raw_time_band!r}"
            )

            # Reject past dates
            if apt_date and apt_date < date.today():
                stats["appointments_failed"] += 1
                stats["errors"].append(f"Row {i+1}: appointment date {apt_date} is in the past — skipped")
                logger.warning(f"Form sync row {i+1}: past date {apt_date} rejected")

            # Attempt booking if we have at least a specialization and a future/today date
            if specialization and apt_date and apt_date >= date.today():
                try:
                    _find_and_book_appointment(
                        booking_service=booking_service,
                        patient_id=patient["patient_id"],
                        specialization=specialization,
                        preferred_doctor_name=preferred_doctor,
                        appointment_date=apt_date,
                        time_band=time_band,
                        reason=reason,
                    )
                    stats["appointments_booked"] += 1
                except Exception as book_exc:
                    stats["appointments_failed"] += 1
                    stats["errors"].append(f"Row {i+1} booking failed: {book_exc}")
                    logger.warning(f"Form sync row {i+1} booking error: {book_exc}")

        except Exception as exc:
            stats["errors"].append(f"Row {i+1}: {exc}")
            logger.error(f"Form sync row {i+1} error: {exc}")

    with _sync_lock:
        _last_synced_row = len(rows)
        _sync_stats["last_sync"] = datetime.now().isoformat()
        _sync_stats["total_new"] += stats["new"]
        _sync_stats["total_skipped"] += stats["skipped"]
        _sync_stats["total_errors"] += len(stats["errors"])
        _sync_stats["total_appointments_booked"] += stats["appointments_booked"]
        _sync_stats["total_appointments_failed"] += stats["appointments_failed"]
        _sync_stats["last_result"] = stats

    return stats


def start_background_sync(booking_service, interval: Optional[int] = None) -> threading.Thread:
    interval = interval or settings.GOOGLE_FORMS_SYNC_INTERVAL

    def _poll_loop():
        logger.info(f"Google Forms sync started — polling every {interval}s")
        while True:
            try:
                result = sync_form_responses(booking_service)
                if result["new"] > 0 or result["appointments_booked"] > 0 or result["errors"]:
                    logger.info(f"Forms sync: {result}")
            except Exception as exc:
                logger.error(f"Forms sync loop error: {exc}", exc_info=True)
            time.sleep(interval)

    thread = threading.Thread(target=_poll_loop, daemon=True, name="gsuite-forms-sync")
    thread.start()
    return thread
