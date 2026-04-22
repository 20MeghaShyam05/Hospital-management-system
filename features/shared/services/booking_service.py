# =============================================================================
# services/booking_service.py
# BookingService — central orchestrator for all appointment operations
# =============================================================================
# NSL coverage : GO1 (register patient), GO2 (register doctor),
#                GO4 (book), GO5 (cancel), GO6 (reschedule),
#                GO8 (report data)
# Failure cases: E8  — lunch block enforced server-side in book_appointment()
#                E9  — past-date guard in book_appointment()
#                E12 — weekend guard in book_appointment()
#                E14 — same patient/same doctor same-day: allowed (multi-appt)
#                F6  — threading.Lock around the full check+book cycle
#                F23 — DB rollback on partial failure
#
# CHANGE: Availability table REMOVED. Slots are generated directly from
#         doctor work hours. set_doctor_availability() removed.
#         Nurse registration and triage operations added.
#
# Advanced Python (assignment spec):
#   - Decorators: @log_action logs every booking mutation
#   - Threading: _booking_lock guards the atomic check+book sequence
#   - Generator: get_appointment_queue_stream() delegates to QueueManager
#   - Magic methods: services compose model objects that carry __repr__/__str__
#   - Lambda / map / filter: used via ScheduleManager helpers
# =============================================================================

from __future__ import annotations

import functools
import logging
import threading
import uuid
from datetime import date, datetime, time, timedelta
from typing import Optional

from config import settings
from features.shared.database.postgres import PostgresManager
from features.shared.database.mongo    import MongoManager
from features.shared.models.appointment import Appointment, AppointmentPriority, AppointmentStatus
from features.shared.models.doctor      import Doctor, Specialization
from features.shared.models.nurse       import Nurse
from features.shared.models.patient     import Patient, Gender, BloodGroup
from features.shared.models.slot        import LUNCH_START, LUNCH_END
from features.shared.models.triage      import Triage, QueueType
from features.shared.services.auth_service import AuthService
from features.shared.services.schedule_manager import ScheduleManager
from features.shared.services.queue_manager    import QueueManager

logger = logging.getLogger(__name__)


# =============================================================================
# Decorator — log every booking action to MongoDB audit trail (Advanced Python)
# =============================================================================

def log_action(action_name: str):
    """Decorator factory: logs method name, meaningful display fields, and outcome to Mongo."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            cu = kwargs.get("current_user", {})
            _uname = cu.get("username") or cu.get("user_id", "system")
            _role  = cu.get("role", "")
            actor  = f"{_uname} ({_role})" if _role else _uname
            try:
                result = fn(self, *args, **kwargs)
                # Extract human-readable fields from the result for display in audit logs
                log_data: dict = {"success": True}
                if isinstance(result, dict):
                    for key in ("full_name", "patient_name", "doctor_name", "nurse_name"):
                        if result.get(key):
                            log_data["name"] = result[key]
                            break
                    for key in ("email", "mobile", "specialization", "appointment_id",
                                "date", "start_time", "status", "priority", "uhid"):
                        if result.get(key) is not None:
                            log_data[key] = str(result[key])
                # For registration events, also capture the name from kwargs if result didn't have it
                if "name" not in log_data and kwargs.get("full_name"):
                    log_data["name"] = kwargs["full_name"]
                self._mongo.log_audit(event=action_name, data=log_data, actor=actor)
                return result
            except Exception as exc:
                fail_data: dict = {"error": str(exc)}
                if kwargs.get("full_name"):
                    fail_data["name"] = kwargs["full_name"]
                if kwargs.get("email"):
                    fail_data["email"] = kwargs["email"]
                self._mongo.log_audit(event=f"{action_name}_failed", data=fail_data, actor=actor)
                raise
        return wrapper
    return decorator


# =============================================================================
# BookingService
# =============================================================================

class BookingService:
    """Orchestrates all patient-facing operations.

    Depends on:
      db       : PostgresManager (with in-memory fallback)
      mongo    : MongoManager    (audit + queue persistence)
      schedule : ScheduleManager (slot queries, cache)
      queue    : QueueManager    (priority queue)

    Threading
    ---------
    _booking_lock guards the critical section:
      1. check slot conflict  (SELECT)
      2. mark slot booked     (UPDATE)
      3. save appointment     (INSERT)
    Steps 1–3 are atomic within one process (F6).
    For multi-process safety, PostgresManager.lock_slot_for_update() uses
    SELECT FOR UPDATE at the DB level.
    """

    def __init__(
        self,
        db:       PostgresManager,
        mongo:    MongoManager,
        schedule: ScheduleManager,
        queue:    QueueManager,
    ) -> None:
        self._db       = db
        self._mongo    = mongo
        self._schedule = schedule
        self._queue    = queue
        self._booking_lock = threading.Lock()

    def _resolve_patient(self, identifier: str) -> Optional[dict]:
        patient = self._db.get_patient_by_id(identifier)
        if patient:
            return patient
        if hasattr(self._db, "get_patient_by_uhid"):
            return self._db.get_patient_by_uhid(identifier)
        return None

    def _resolve_doctor(self, identifier: str) -> Optional[dict]:
        doctor = self._db.get_doctor_by_id(identifier)
        if doctor:
            return doctor
        if hasattr(self._db, "get_doctor_by_uhid"):
            return self._db.get_doctor_by_uhid(identifier)
        return None

    def _resolve_nurse(self, identifier: str) -> Optional[dict]:
        nurse = self._db.get_nurse_by_id(identifier)
        if nurse:
            return nurse
        if hasattr(self._db, "get_nurse_by_uhid"):
            return self._db.get_nurse_by_uhid(identifier)
        return None

    @staticmethod
    def _slot_date_iso(slot_dict: dict) -> str:
        slot_date = slot_dict["date"]
        return slot_date.isoformat() if hasattr(slot_date, "isoformat") else str(slot_date)

    @staticmethod
    def _slot_time_value(value: time | str) -> time:
        return time.fromisoformat(value) if isinstance(value, str) else value

    def _validate_slot_matches_request(
        self,
        slot_dict: dict,
        doctor_id: str,
        appointment_date: date,
    ) -> None:
        if slot_dict["doctor_id"] != doctor_id:
            raise ValueError("Selected slot does not belong to the requested doctor.")
        if self._slot_date_iso(slot_dict) != appointment_date.isoformat():
            raise ValueError("Selected slot does not belong to the requested appointment date.")

    def _send_registration_email(self, *, role_label: str, saved_record: dict) -> None:
        """Send a non-blocking registration confirmation email if an address is available."""
        email = saved_record.get("email")
        if not email:
            return

        entity_id = (
            saved_record.get("patient_id")
            or saved_record.get("doctor_id")
            or saved_record.get("nurse_id")
            or ""
        )

        try:
            from features.gsuite.gmail_service import get_gmail

            get_gmail().send_registration_success(
                email,
                {
                    "role_label": role_label,
                    "full_name": saved_record.get("full_name", ""),
                    "email": email,
                    "mobile": saved_record.get("mobile", ""),
                    "entity_id": entity_id,
                    "uhid": saved_record.get("uhid", ""),
                },
            )
        except Exception:
            logger.debug("%s registration email skipped", role_label, exc_info=True)

    def _send_booking_confirmation_email(
        self,
        *,
        patient_data: Optional[dict],
        doctor_data: Optional[dict],
        appointment_date: date,
        start_time: time,
        queue_position: int,
        appointment_id: str,
    ) -> None:
        if not patient_data or not patient_data.get("email"):
            return
        try:
            from features.gsuite.gmail_service import get_gmail

            get_gmail().send_appointment_confirmation(
                patient_data["email"],
                {
                    "patient_name": patient_data.get("full_name", ""),
                    "doctor_name": doctor_data.get("full_name", "") if doctor_data else "",
                    "date": str(appointment_date),
                    "time": str(start_time),
                    "queue_position": queue_position,
                    "appointment_id": appointment_id,
                },
            )
        except Exception:
            logger.warning("Immediate booking confirmation email failed", exc_info=True)

    def _send_cancellation_email(
        self,
        *,
        patient_data: Optional[dict],
        doctor_data: Optional[dict],
        appointment_date: date,
        reason: str,
    ) -> None:
        if not patient_data or not patient_data.get("email"):
            return
        try:
            from features.gsuite.gmail_service import get_gmail

            get_gmail().send_cancellation_notice(
                patient_data["email"],
                {
                    "patient_name": patient_data.get("full_name", ""),
                    "doctor_name": doctor_data.get("full_name", "") if doctor_data else "",
                    "date": str(appointment_date),
                    "reason": reason or "Not specified",
                },
            )
        except Exception:
            logger.warning("Immediate cancellation email failed", exc_info=True)

    def _send_reschedule_email(
        self,
        *,
        patient_data: Optional[dict],
        doctor_data: Optional[dict],
        new_date: date,
        new_time: time,
    ) -> None:
        if not patient_data or not patient_data.get("email"):
            return
        try:
            from features.gsuite.gmail_service import get_gmail

            get_gmail().send_reschedule_notice(
                patient_data["email"],
                {
                    "patient_name": patient_data.get("full_name", ""),
                    "doctor_name": doctor_data.get("full_name", "") if doctor_data else "",
                    "new_date": str(new_date),
                    "new_time": str(new_time),
                },
            )
        except Exception:
            logger.warning("Immediate reschedule email failed", exc_info=True)

    # =========================================================================
    # GO1 — Register / look up patient
    # =========================================================================

    @log_action("patient_registered")
    def register_patient(
        self,
        full_name: str,
        email: str,
        mobile: str,
        date_of_birth: Optional[date] = None,
        gender: Optional[str] = None,
        blood_group: Optional[str] = None,
        address: Optional[str] = None,
        registered_by: Optional[str] = None,
        *,
        current_user: dict = {},
    ) -> dict:
        """Register a new patient or return the existing record (R012).

        Existing patient check (R001, R002):
          1. Look up by email — if found, update name and return (E1).
          2. Look up by mobile — if found, return existing (E3: shared phone ok).
          3. Neither found → create new.

        Returns the patient dict (new or existing).
        """
        # Check by email first (R001)
        existing = self._db.get_patient_by_email(email)
        if existing:
            logger.info(f"Existing patient found by email: {existing['patient_id']}")
            if not existing.get("uhid"):
                existing["uhid"] = Patient.generate_uhid()
            existing["visit_count"] = existing.get("visit_count", 0) + 1
            existing["visit_type"]  = "returning_patient" if existing["visit_count"] > 1 else "first_visit"
            return self._db.upsert_patient(existing)

        # Model-level validation runs in Patient.__init__
        gender_val     = Gender(gender)     if gender     else None
        blood_grp_val  = BloodGroup(blood_group) if blood_group else None

        patient = Patient(
            full_name=full_name,
            email=email,
            mobile=mobile,
            date_of_birth=date_of_birth,
            gender=gender_val,
            blood_group=blood_grp_val,
            address=address,
            registered_by=registered_by,
        )
        patient_dict = patient.to_dict()
        patient_dict["password_hash"] = AuthService.hash_password(patient.mobile)
        patient_dict["password_changed_at"] = datetime.now().isoformat()
        saved = self._db.upsert_patient(patient_dict)
        logger.info(f"New patient registered: {patient.patient_id}")
        self._send_registration_email(role_label="Patient", saved_record=saved)
        return saved

    def get_patient(self, patient_id: str) -> Optional[dict]:
        return self._resolve_patient(patient_id)

    def get_patient_by_email(self, email: str) -> Optional[dict]:
        return self._db.get_patient_by_email(email)

    def list_patients(self, active_only: bool = True) -> list[dict]:
        return self._db.list_patients(active_only)

    # =========================================================================
    # GO2 — Register / look up doctor
    # =========================================================================

    @log_action("doctor_registered")
    def register_doctor(
        self,
        full_name: str,
        email: str,
        mobile: str,
        specialization: str,
        max_patients_per_day: int = 20,
        work_start_time: Optional[time] = None,
        work_end_time: Optional[time] = None,
        consultation_duration_minutes: Optional[int] = None,
        *,
        current_user: dict = {},
    ) -> dict:
        """Register a new doctor or update existing by email (E7).

        Validation (R021–R023) runs inside Doctor.__init__.
        Work times default from SPECIALIZATION_WORK_HOURS config.
        Consultation duration defaults from SPECIALIZATION_CONSULTATION_MINUTES.

        After registration, automatically generates slots for the next 5 weekdays.
        """
        existing_doctor = self._db.get_doctor_by_email(email)
        doctor = Doctor(
            full_name=full_name,
            email=email,
            mobile=mobile,
            specialization=Specialization(specialization),
            max_patients_per_day=max_patients_per_day,
            work_start_time=work_start_time,
            work_end_time=work_end_time,
            consultation_duration_minutes=consultation_duration_minutes,
        )
        doctor_dict = doctor.to_dict()
        doctor_dict["password_hash"] = AuthService.hash_password(doctor.mobile)
        doctor_dict["password_changed_at"] = datetime.now().isoformat()
        saved = self._db.upsert_doctor(doctor_dict)
        logger.info(f"Doctor registered/updated: {doctor.doctor_id}")

        # --- AUTO-GENERATE SLOTS for upcoming weekdays ---
        self._auto_generate_slots(saved)
        if not existing_doctor:
            self._send_registration_email(role_label="Doctor", saved_record=saved)

        return saved

    def _auto_generate_slots(self, doctor_dict: dict) -> None:
        """Auto-generate slots for the next N weekdays.

        Uses the doctor's own work_start_time, work_end_time, and
        consultation_duration_minutes (which default from their
        specialization config). Generates directly — no availability table.
        """
        try:
            self._schedule.generate_weekly_slots(doctor_dict)
        except Exception as e:
            logger.warning(f"Auto-slot generation failed for {doctor_dict.get('doctor_id')}: {e}")

    def get_doctor(self, doctor_id: str) -> Optional[dict]:
        return self._resolve_doctor(doctor_id)

    def list_doctors(self, active_only: bool = True) -> list[dict]:
        return self._db.list_doctors(active_only)

    # =========================================================================
    # Nurse Registration
    # =========================================================================

    @log_action("nurse_registered")
    def register_nurse(
        self,
        full_name: str,
        email: str,
        mobile: str,
        *,
        current_user: dict = {},
    ) -> dict:
        """Register a new nurse or update existing by email."""
        existing_nurse = self._db.get_nurse_by_email(email)
        nurse = Nurse(
            full_name=full_name,
            email=email,
            mobile=mobile,
        )
        nurse_dict = nurse.to_dict()
        nurse_dict["password_hash"] = AuthService.hash_password(nurse.mobile)
        nurse_dict["password_changed_at"] = datetime.now().isoformat()
        nurse_dict["is_active"] = True
        nurse_dict["created_at"] = datetime.now().isoformat()
        saved = self._db.upsert_nurse(nurse_dict)
        logger.info(f"Nurse registered/updated: {nurse.nurse_id}")
        if not existing_nurse:
            self._send_registration_email(role_label="Nurse", saved_record=saved)
        return saved

    def get_nurse(self, nurse_id: str) -> Optional[dict]:
        return self._resolve_nurse(nurse_id)

    def list_nurses(self, active_only: bool = True) -> list[dict]:
        return self._db.list_nurses(active_only)

    # =========================================================================
    # Triage Operations
    # =========================================================================

    @log_action("triage_recorded")
    def create_triage_entry(
        self,
        patient_id: str,
        nurse_id: str,
        doctor_id: str,
        triage_date: date,
        queue_type: str = "normal",
        appointment_id: Optional[str] = None,
        blood_pressure: Optional[str] = None,
        heart_rate: Optional[int] = None,
        temperature: Optional[float] = None,
        weight: Optional[float] = None,
        oxygen_saturation: Optional[float] = None,
        symptoms: Optional[str] = None,
        notes: Optional[str] = None,
        *,
        current_user: dict = {},
    ) -> dict:
        """Record patient vitals and assign to queue.

        The nurse records vitals and decides whether the patient goes to
        the normal (FIFO) or emergency (priority) queue.

        If appointment_id is provided, updates the appointment's priority
        and the queue entry's is_emergency flag accordingly.
        """
        # Validate entities exist
        patient = self._resolve_patient(patient_id)
        if not patient:
            raise ValueError(f"Patient {patient_id} not found.")
        patient_id = patient["patient_id"]

        nurse = self._resolve_nurse(nurse_id)
        if not nurse:
            raise ValueError(f"Nurse {nurse_id} not found.")
        nurse_id = nurse["nurse_id"]

        doctor = self._resolve_doctor(doctor_id)
        if not doctor:
            raise ValueError(f"Doctor {doctor_id} not found.")
        doctor_id = doctor["doctor_id"]

        apt_dict = None
        if appointment_id:
            apt_dict = self._db.get_appointment(appointment_id)
            if not apt_dict:
                raise ValueError(f"Appointment {appointment_id} not found.")
            if apt_dict["patient_id"] != patient_id or apt_dict["doctor_id"] != doctor_id:
                raise ValueError("Triage patient and doctor must match the appointment.")
            if apt_dict["status"] not in ("booked", "rescheduled"):
                raise ValueError("Only active appointments can be sent to the queue.")
            if triage_date.isoformat() != str(apt_dict["date"]):
                raise ValueError("Vitals must be recorded on the appointment date.")

            appointment_start = self._slot_time_value(apt_dict["start_time"])
            if triage_date == date.today() and datetime.now().time() > appointment_start:
                raise ValueError("Vitals cannot be recorded after the appointment start time.")

        # Create triage model (validates vitals ranges)
        triage = Triage(
            patient_id=patient_id,
            nurse_id=nurse_id,
            doctor_id=doctor_id,
            date=triage_date,
            queue_type=QueueType(queue_type),
            appointment_id=appointment_id,
            blood_pressure=blood_pressure,
            heart_rate=heart_rate,
            temperature=temperature,
            weight=weight,
            oxygen_saturation=oxygen_saturation,
            symptoms=symptoms,
            notes=notes,
        )
        saved = self._db.save_triage(triage.to_dict())

        if appointment_id and apt_dict:
            apt = Appointment.from_dict(apt_dict)
            apt.priority = AppointmentPriority(queue_type)
            updated_apt = self._db.update_appointment(apt.to_dict())
            self._mongo.store_analytics_snapshot(updated_apt)

            existing_queue = self._queue.get_queue(doctor_id, triage_date)
            if not any(entry.appointment_id == appointment_id for entry in existing_queue):
                queue_entry = self._queue.enqueue(
                    doctor_id=doctor_id,
                    for_date=triage_date,
                    patient_id=patient_id,
                    appointment_id=appointment_id,
                    is_emergency=(queue_type == "emergency"),
                )
                saved["queue_position"] = queue_entry.queue_position

        logger.info(
            f"Triage recorded: patient={patient_id}, nurse={nurse_id}, "
            f"queue_type={queue_type}"
        )
        return saved

    def get_triage_entries(self, patient_id: str) -> list[dict]:
        patient = self._resolve_patient(patient_id)
        if not patient:
            return []
        return self._db.get_triage_for_patient(patient["patient_id"])

    def get_triage_for_date(self, triage_date: date, doctor_id: Optional[str] = None) -> list[dict]:
        resolved_doctor_id = None
        if doctor_id:
            doctor = self._resolve_doctor(doctor_id)
            if not doctor:
                return []
            resolved_doctor_id = doctor["doctor_id"]
        return self._db.get_triage_for_date(triage_date.isoformat(), resolved_doctor_id)

    # =========================================================================
    # Slot queries (auto-generate on demand)
    # =========================================================================

    def get_available_slots(self, doctor_id: str, for_date: date) -> list[dict]:
        """Proxy to ScheduleManager with slot_time_labels attached.

        Auto-generates slots if they don't exist yet for this date.
        """
        doctor = self._resolve_doctor(doctor_id)
        if not doctor:
            raise ValueError(f"Doctor {doctor_id} not found.")

        # Auto-generate slots on-demand if none exist
        if not self._db.has_slots_for_doctor_date(doctor["doctor_id"], for_date.isoformat()):
            if for_date >= date.today() and for_date.weekday() not in (5, 6):
                try:
                    self._schedule.generate_daily_slots(doctor, for_date)
                except Exception as e:
                    logger.warning(f"On-demand slot generation failed: {e}")

        slots = self._schedule.get_available_slots(doctor["doctor_id"], for_date)
        labels = self._schedule.slot_time_labels(slots)
        for slot, label in zip(slots, labels):
            slot["label"] = label
        return slots

    def get_all_slots_for_display(self, doctor_id: str, for_date: date) -> list[dict]:
        doctor = self._resolve_doctor(doctor_id)
        if not doctor:
            raise ValueError(f"Doctor {doctor_id} not found.")
        if not self._db.has_slots_for_doctor_date(doctor["doctor_id"], for_date.isoformat()):
            if for_date >= date.today() and for_date.weekday() not in (5, 6):
                self._schedule.generate_daily_slots(doctor, for_date)
        slots = self._schedule.get_all_slots_for_display(doctor["doctor_id"], for_date)
        labels = self._schedule.slot_time_labels(slots)
        for slot, label in zip(slots, labels):
            slot["label"] = label
        return slots

    def get_slot(self, slot_id: str) -> Optional[dict]:
        return self._db.get_slot(slot_id)

    def set_slot_blocked(self, slot_id: str, is_blocked: bool) -> dict:
        slot = self._db.get_slot(slot_id)
        if not slot:
            raise ValueError(f"Slot {slot_id} not found.")
        if slot.get("is_booked") and is_blocked:
            raise ValueError("Booked slots cannot be blocked.")
        if not self._db.update_slot_blocked(slot_id, is_blocked):
            raise ValueError("Unable to update slot block status.")
        updated = self._db.get_slot(slot_id)
        if updated:
            self._schedule.invalidate_cache(updated["doctor_id"], self._slot_date_iso(updated))
            return updated
        raise ValueError(f"Slot {slot_id} not found after update.")

    # =========================================================================
    # GO4 — Book appointment (most complex — F6, E8, E9, E12)
    # =========================================================================

    @log_action("appointment_booked")
    def book_appointment(
        self,
        patient_id:       str,
        doctor_id:        str,
        slot_id:          str,
        appointment_date: date,
        notes:            Optional[str] = None,
        priority:         str = "normal",
        booked_by:        Optional[str] = None,
        *,
        current_user: dict = {},
    ) -> dict:
        """Book an appointment — atomic check + lock + insert (F6).

        Enforces:
          E8  — lunch time blocked server-side (not just UI)
          E9  — past date rejected
          E12 — weekend rejected
          R071 — double booking prevented
          R072 — slot must still be available at confirmation time
          R073 — patient must be active
          R074 — emergency triggers priority queue
        """
        # ---- Pre-lock validations (cheap, no DB write) -------------------

        # E9 — past date
        if appointment_date < date.today():
            raise ValueError("Cannot book an appointment for a past date.")

        # E12 — weekend
        if self._schedule.is_weekend(appointment_date):
            raise ValueError(
                f"{appointment_date} is a weekend. "
                "Please select a weekday for your appointment."
            )

        # Patient must be active (R073)
        patient_dict = self._resolve_patient(patient_id)
        if not patient_dict:
            raise ValueError(f"Patient {patient_id} not found.")
        if not patient_dict.get("is_active", True):
            raise ValueError("Patient account is inactive.")
        patient_id = patient_dict["patient_id"]

        # Doctor must be active
        doctor_dict = self._resolve_doctor(doctor_id)
        if not doctor_dict:
            raise ValueError(f"Doctor {doctor_id} not found.")
        if not doctor_dict.get("is_active", True):
            raise ValueError(f"Doctor {doctor_id} is inactive.")
        doctor_id = doctor_dict["doctor_id"]

        # ---- Atomic section: check + lock + write (F6) -------------------
        with self._booking_lock:
            # Fetch slot — lock at PG level if available (SELECT FOR UPDATE)
            slot_dict = (
                self._db.lock_slot_for_update(slot_id)
                if hasattr(self._db, "lock_slot_for_update")
                else self._db.get_slot(slot_id)
            )

            if not slot_dict:
                # Slot doesn't exist or already taken
                suggestion = self._schedule.find_next_available_slot(
                    doctor_id, appointment_date
                )
                raise ValueError(
                    "This slot is no longer available (R072). "
                    + (f"Next available: {suggestion['date']} at {suggestion['start_time']}" if suggestion else "No upcoming slots found.")
                )

            self._validate_slot_matches_request(slot_dict, doctor_id, appointment_date)

            if slot_dict.get("is_booked") or slot_dict.get("is_blocked"):
                raise ValueError("Selected slot is not available for booking.")

            # E8 — lunch block server-side
            start_t = self._slot_time_value(slot_dict["start_time"])
            end_t   = self._slot_time_value(slot_dict["end_time"])
            if self._schedule.is_lunch_time(start_t, end_t):
                raise ValueError(
                    "Slot falls within the lunch break (1:00 PM – 1:30 PM). "
                    "Please select a different time."
                )

            # R071 — double booking: same patient, same slot
            if self._db.check_slot_conflict(slot_id):
                suggestion = self._schedule.find_next_available_slot(
                    doctor_id, appointment_date
                )
                raise ValueError(
                    "This slot was just booked by someone else (R072). "
                    + (f"Next available: {suggestion['date']} at {suggestion['start_time']}" if suggestion else "")
                )

            # Build and save appointment
            apt = Appointment(
                patient_id=patient_id,
                doctor_id=doctor_id,
                slot_id=slot_id,
                date=appointment_date,
                start_time=start_t,
                end_time=end_t,
                priority=AppointmentPriority(priority),
                notes=notes,
                booked_by=booked_by,
            )

            # Mark slot booked (NF5)
            self._db.update_slot_booked(slot_id, True)
            self._schedule.invalidate_cache(doctor_id, appointment_date.isoformat())

            # Save appointment
            saved_apt = self._db.save_appointment(apt.to_dict())

        # ---- Outside lock: analytics + notifications (non-critical) -------

        # Analytics snapshot for Step 7 DS layer
        self._mongo.store_analytics_snapshot(saved_apt)

        # Estimated wait time (F11 note: slot-duration proxy)
        slot_duration = int(
            (datetime.combine(date.today(), end_t) - datetime.combine(date.today(), start_t))
            .total_seconds() // 60
        )
        wait_minutes = None

        logger.info(
            f"Booked: {apt.appointment_id} | patient={patient_id} | "
            f"doctor={doctor_id} | {appointment_date} {start_t} | awaiting triage"
        )

        result = {
            **saved_apt,
            "queue_position":    None,
            "estimated_wait_min": wait_minutes,
            "next_slot_suggestion": None,
        }

        patient_data = self._resolve_patient(patient_id)
        doctor_data = self._resolve_doctor(doctor_id)
        self._send_booking_confirmation_email(
            patient_data=patient_data,
            doctor_data=doctor_data,
            appointment_date=appointment_date,
            start_time=start_t,
            queue_position=0,
            appointment_id=apt.appointment_id,
        )

        try:
            from features.gsuite.calendar_service import get_calendar
            calendar_result = get_calendar().create_appointment_event(
                doctor_name=doctor_data.get("full_name", "") if doctor_data else "",
                patient_name=patient_data.get("full_name", "") if patient_data else "",
                appointment_date=str(appointment_date),
                start_time=str(start_t),
                duration_minutes=slot_duration,
                patient_email=patient_data.get("email") if patient_data else None,
                doctor_email=doctor_data.get("email") if doctor_data else None,
                appointment_id=apt.appointment_id,
            )
            if calendar_result:
                result["calendar_event_id"] = calendar_result.get("event_id")
                result["calendar_event_link"] = calendar_result.get("link")
                saved_apt["calendar_event_id"] = calendar_result.get("event_id")
                saved_apt["calendar_event_link"] = calendar_result.get("link")
                updated_result = self._db.update_appointment(result)
                result = {
                    **updated_result,
                    "queue_position": None,
                    "estimated_wait_min": wait_minutes,
                    "next_slot_suggestion": None,
                }
        except Exception:
            logger.debug("Calendar event creation skipped", exc_info=True)

        return result

    # =========================================================================
    # GO5 — Cancel appointment
    # =========================================================================

    @log_action("appointment_cancelled")
    def cancel_appointment(
        self,
        appointment_id: str,
        reason: str,
        cancelled_by: Optional[str] = None,
        *,
        current_user: dict = {},
    ) -> dict:
        """Cancel a booked appointment.

        Enforces:
          R091 — cannot cancel past appointments
          R092 — reason >= 10 chars
          R093 — slot released immediately
          R102 — queue reordered after cancellation
        """
        apt_dict = self._db.get_appointment(appointment_id)
        if not apt_dict:
            raise ValueError(f"Appointment {appointment_id} not found.")

        # Restore model to run cancel() state machine
        apt = Appointment.from_dict(apt_dict)
        apt.cancel(reason=reason, cancelled_by=cancelled_by)   # R091/R092/R100

        # Release slot (R093)
        self._db.update_slot_booked(apt.slot_id, False)
        self._schedule.invalidate_cache(apt.doctor_id, apt.date.isoformat())

        # Update appointment record
        saved = self._db.update_appointment(apt.to_dict())

        # Remove from queue (R102) — QueueManager handles reordering internally
        self._queue.cancel_entry(apt.doctor_id, apt.date, appointment_id)

        # Analytics update
        self._mongo.store_analytics_snapshot(saved)

        logger.info(f"Cancelled: {appointment_id} by {cancelled_by}")

        patient_data = self._resolve_patient(apt.patient_id)
        doctor_data = self._resolve_doctor(apt.doctor_id)
        self._send_cancellation_email(
            patient_data=patient_data,
            doctor_data=doctor_data,
            appointment_date=apt.date,
            reason=reason,
        )
        try:
            from features.gsuite.calendar_service import get_calendar
            if saved.get("calendar_event_id"):
                get_calendar().cancel_event(saved["calendar_event_id"])
        except Exception:
            logger.debug("Calendar cancellation skipped", exc_info=True)

        return saved

    # =========================================================================
    # GO6 — Reschedule appointment
    # =========================================================================

    @log_action("appointment_rescheduled")
    def reschedule_appointment(
        self,
        appointment_id: str,
        new_slot_id:    str,
        new_date:       date,
        *,
        current_user: dict = {},
    ) -> dict:
        """Reschedule to a new slot with the same doctor (R121).

        Enforces:
          R111/R120 — max 2 reschedules
          R121 — same doctor only
          R122 — atomic slot swap (release old → lock new)
        """
        apt_dict = self._db.get_appointment(appointment_id)
        if not apt_dict:
            raise ValueError(f"Appointment {appointment_id} not found.")

        apt = Appointment.from_dict(apt_dict)

        # R111 — reschedule count check (also in model, double-checked here)
        if apt.reschedule_count >= settings.MAX_RESCHEDULES:
            raise ValueError(
                f"Maximum {settings.MAX_RESCHEDULES} reschedules reached. "
                "Please cancel and rebook."
            )

        # Fetch new slot
        new_slot = self._db.get_slot(new_slot_id)
        if not new_slot:
            raise ValueError(f"Slot {new_slot_id} not found.")
        self._validate_slot_matches_request(new_slot, apt.doctor_id, new_date)
        if new_slot["is_booked"] or new_slot["is_blocked"]:
            raise ValueError(f"Slot {new_slot_id} is not available for booking.")
        if new_slot["is_lunch_break"]:
            raise ValueError("Cannot reschedule into the lunch break slot.")

        # R121 — same doctor
        if new_slot["doctor_id"] != apt.doctor_id:
            raise ValueError(
                "Rescheduling must be with the same doctor (R121). "
                f"New slot belongs to {new_slot['doctor_id']}."
            )

        # E9 — past date
        if new_date < date.today():
            raise ValueError("Cannot reschedule to a past date.")

        # E12 — weekend
        if self._schedule.is_weekend(new_date):
            raise ValueError("Cannot reschedule to a weekend.")

        new_start = self._slot_time_value(new_slot["start_time"])
        new_end   = self._slot_time_value(new_slot["end_time"])

        with self._booking_lock:   # R122 — atomic slot swap
            old_slot_id = apt.slot_id
            old_date    = apt.date

            # Conflict check on new slot
            if self._db.check_slot_conflict(new_slot_id):
                raise ValueError(f"Slot {new_slot_id} was just booked by someone else.")

            # Lock new slot first
            self._db.update_slot_booked(new_slot_id, True)

            # Release old slot
            self._db.update_slot_booked(old_slot_id, False)

            # Update appointment model
            apt.reschedule(
                new_slot_id=new_slot_id,
                new_date=new_date,
                new_start_time=new_start,
                new_end_time=new_end,
            )
            saved = self._db.update_appointment(apt.to_dict())

        # Invalidate caches for both old and new dates
        self._schedule.invalidate_cache(apt.doctor_id, old_date.isoformat())
        self._schedule.invalidate_cache(apt.doctor_id, new_date.isoformat())

        # Update queue — cancel old entry, create new one
        self._queue.cancel_entry(apt.doctor_id, old_date, appointment_id)
        self._queue.enqueue(
            doctor_id=apt.doctor_id,
            for_date=new_date,
            patient_id=apt.patient_id,
            appointment_id=appointment_id,
            is_emergency=apt.is_emergency,
        )

        self._mongo.store_analytics_snapshot(saved)
        logger.info(
            f"Rescheduled: {appointment_id} → "
            f"{new_date} {new_start} (slot {new_slot_id})"
        )

        patient_data = self._resolve_patient(apt.patient_id)
        doctor_data = self._resolve_doctor(apt.doctor_id)
        self._send_reschedule_email(
            patient_data=patient_data,
            doctor_data=doctor_data,
            new_date=new_date,
            new_time=new_start,
        )
        try:
            from features.gsuite.calendar_service import get_calendar
            if saved.get("calendar_event_id"):
                calendar_result = get_calendar().update_event_time(
                    saved["calendar_event_id"],
                    new_date.isoformat(),
                    new_start.isoformat(),
                    int(
                        (
                            datetime.combine(date.today(), new_end)
                            - datetime.combine(date.today(), new_start)
                        ).total_seconds() // 60
                    ),
                )
                if calendar_result:
                    saved["calendar_event_link"] = calendar_result.get("link")
                    saved = self._db.update_appointment(saved)
        except Exception:
            logger.debug("Calendar reschedule skipped", exc_info=True)

        return saved

    # =========================================================================
    # GO7 — Queue operations (proxy to QueueManager)
    # =========================================================================

    def get_queue(self, doctor_id: str, for_date: date) -> list[dict]:
        doctor = self._resolve_doctor(doctor_id)
        if not doctor:
            raise ValueError(f"Doctor {doctor_id} not found.")
        entries = self._queue.get_queue(doctor["doctor_id"], for_date)
        return [e.to_dict() for e in entries]

    def get_queue_summary(self, doctor_id: str, for_date: date) -> dict:
        doctor = self._resolve_doctor(doctor_id)
        if not doctor:
            raise ValueError(f"Doctor {doctor_id} not found.")
        return self._queue.get_queue_summary(doctor["doctor_id"], for_date)

    def call_next_patient(self, doctor_id: str, for_date: date) -> Optional[dict]:
        doctor = self._resolve_doctor(doctor_id)
        if not doctor:
            raise ValueError(f"Doctor {doctor_id} not found.")
        entry = self._queue.dequeue(doctor["doctor_id"], for_date)
        return entry.to_dict() if entry else None

    def complete_appointment(
        self, doctor_id: str, appointment_id: str
    ) -> dict:
        """Mark appointment completed via queue (GO7 LO3)."""
        doctor = self._resolve_doctor(doctor_id)
        if not doctor:
            raise ValueError(f"Doctor {doctor_id} not found.")
        queue_entry = self._queue.complete(doctor["doctor_id"], appointment_id)
        apt_dict = self._db.get_appointment(appointment_id)
        if apt_dict:
            apt = Appointment.from_dict(apt_dict)
            apt.complete()
            apt_dict = self._db.update_appointment(apt.to_dict())
            self._mongo.store_analytics_snapshot(apt_dict)
        return queue_entry.to_dict()

    def mark_no_show(self, doctor_id: str, appointment_id: str) -> dict:
        """Mark no-show via queue (GO7 LO3)."""
        doctor = self._resolve_doctor(doctor_id)
        if not doctor:
            raise ValueError(f"Doctor {doctor_id} not found.")
        queue_entry = self._queue.mark_no_show(doctor["doctor_id"], appointment_id)
        apt_dict = self._db.get_appointment(appointment_id)
        if apt_dict:
            apt = Appointment.from_dict(apt_dict)
            apt.mark_no_show()
            apt_dict = self._db.update_appointment(apt.to_dict())
            self._mongo.store_analytics_snapshot(apt_dict)
        return queue_entry.to_dict()

    def create_prescription(
        self,
        appointment_id: str,
        diagnosis: str,
        medicines: str,
        advice: Optional[str] = None,
        follow_up_date: Optional[date] = None,
        *,
        current_user: dict = {},
    ) -> dict:
        apt_dict = self._db.get_appointment(appointment_id)
        if not apt_dict:
            raise ValueError(f"Appointment {appointment_id} not found.")
        if apt_dict.get("status") != "completed":
            raise ValueError("Prescription can be created only after the appointment is completed.")

        doctor = self._resolve_doctor(apt_dict["doctor_id"])
        patient = self._resolve_patient(apt_dict["patient_id"])
        doc = {
            "prescription_id": f"RX-{uuid.uuid4().hex[:10].upper()}",
            "appointment_id": appointment_id,
            "patient_id": apt_dict["patient_id"],
            "doctor_id": apt_dict["doctor_id"],
            "doctor_specialization": doctor.get("specialization") if doctor else None,
            "patient_name": patient.get("full_name") if patient else None,
            "doctor_name": doctor.get("full_name") if doctor else None,
            "diagnosis": diagnosis,
            "medicines": medicines,
            "advice": advice,
            "follow_up_date": follow_up_date.isoformat() if follow_up_date else None,
            "created_by": current_user.get("user_id", "system"),
            "created_at": datetime.now().isoformat(),
        }
        return self._mongo.save_prescription(doc)

    def get_patient_prescriptions(self, patient_id: str) -> list[dict]:
        patient = self._resolve_patient(patient_id)
        if not patient:
            return []
        return self._mongo.get_prescriptions_for_patient(patient["patient_id"])

    def get_doctor_prescriptions(self, doctor_id: str) -> list[dict]:
        doctor = self._resolve_doctor(doctor_id)
        if not doctor:
            return []
        return self._mongo.get_prescriptions_for_doctor(doctor["doctor_id"])

    def estimate_wait(
        self, doctor_id: str, for_date: date, appointment_id: str, slot_duration: int = 15
    ) -> int:
        doctor = self._resolve_doctor(doctor_id)
        if not doctor:
            raise ValueError(f"Doctor {doctor_id} not found.")
        return self._queue.estimate_wait_minutes(
            doctor["doctor_id"], for_date, appointment_id, slot_duration
        )

    def triage_groups(
        self, doctor_id: str, for_date: date, capacity: int = 5
    ) -> list[dict]:
        doctor = self._resolve_doctor(doctor_id)
        if not doctor:
            raise ValueError(f"Doctor {doctor_id} not found.")
        groups = self._queue.triage_groups(doctor["doctor_id"], for_date, capacity)
        return [
            {**g, "entries": [e.to_dict() for e in g["entries"]]}
            for g in groups
        ]

    # Generator proxy — DSA requirement surfaced at service layer
    def get_appointment_queue_stream(self, doctor_id: str, for_date: date):
        """Yield queue entries as dicts (generator wrapper)."""
        doctor = self._resolve_doctor(doctor_id)
        if not doctor:
            raise ValueError(f"Doctor {doctor_id} not found.")
        for entry in self._queue.stream_queue(doctor["doctor_id"], for_date):
            yield entry.to_dict()

    # =========================================================================
    # Appointment read queries
    # =========================================================================

    def get_appointment(self, appointment_id: str) -> Optional[dict]:
        return self._db.get_appointment(appointment_id)

    def get_patient_appointments(self, patient_id: str) -> list[dict]:
        patient = self._resolve_patient(patient_id)
        if not patient:
            return []
        return self._db.get_appointments_for_patient(patient["patient_id"])

    def get_doctor_appointments(
        self,
        doctor_id: str,
        for_date: date,
        status_filter: Optional[list[str]] = None,
    ) -> list[dict]:
        doctor = self._resolve_doctor(doctor_id)
        if not doctor:
            return []
        return self._db.get_appointments_for_doctor_date(
            doctor["doctor_id"], for_date.isoformat(), status_filter
        )

    def get_all_appointments(
        self,
        for_date: Optional[date] = None,
        doctor_id: Optional[str] = None,
        status_filter: Optional[list[str]] = None,
    ) -> list[dict]:
        resolved_doctor_id = None
        if doctor_id:
            doctor = self._resolve_doctor(doctor_id)
            if not doctor:
                return []
            resolved_doctor_id = doctor["doctor_id"]
        return self._db.get_all_appointments(
            for_date.isoformat() if for_date else None,
            resolved_doctor_id,
            status_filter,
        )

    # =========================================================================
    # GO8 — Report data
    # =========================================================================

    def get_report_data(
        self, report_date: date, doctor_id: Optional[str] = None
    ) -> dict:
        """Aggregate report metrics (GO8 LO2 NF1–NF9).

        Delegates to DB layer; enriches with doctor name if available.
        """
        if report_date > date.today():
            raise ValueError("Cannot generate report for a future date (R141).")

        resolved_doctor_id = None
        if doctor_id:
            doctor = self._resolve_doctor(doctor_id)
            if not doctor:
                raise ValueError(f"Doctor {doctor_id} not found.")
            resolved_doctor_id = doctor["doctor_id"]

        report = self._db.get_report_data(report_date.isoformat(), resolved_doctor_id)

        # Enrich busiest doctor with name
        if report.get("busiest_doctor_id"):
            doc = self._db.get_doctor_by_id(report["busiest_doctor_id"])
            if doc:
                report["busiest_doctor_name"] = doc["full_name"]
                report["busiest_doctor_specialization"] = doc["specialization"]

        # Peak hour → human-readable label
        if report.get("peak_hour") is not None:
            h = int(report["peak_hour"])
            report["peak_hour_label"] = (
                f"{h:02d}:00 – {(h+1):02d}:00"
            )

        return report

    def get_analytics_data(
        self, start_date: date, end_date: date, doctor_id: Optional[str] = None
    ) -> list[dict]:
        """Raw appointment docs for Pandas/NumPy (Step 7 DS layer)."""
        resolved_doctor_id = None
        if doctor_id:
            doctor = self._resolve_doctor(doctor_id)
            if not doctor:
                raise ValueError(f"Doctor {doctor_id} not found.")
            resolved_doctor_id = doctor["doctor_id"]
        return self._mongo.get_analytics_for_date_range(
            start_date.isoformat(), end_date.isoformat(), resolved_doctor_id
        )
