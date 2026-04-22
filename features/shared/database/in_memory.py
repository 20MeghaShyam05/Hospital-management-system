# =============================================================================
# database/in_memory.py
# InMemoryStore — zero-dependency in-process data store
# =============================================================================
# Role in the architecture
# ------------------------
# 1. PRIMARY store when neither PostgreSQL nor MongoDB is reachable (F2, F3).
# 2. FALLBACK target that PostgresManager and MongoManager delegate to
#    when their connections fail.
# 3. TEST store — unit tests import this directly so no real DB is needed.
#
# Limitations (acknowledged from failure_and_edge_cases.docx)
# -----------------------------------------------------------
# - Data is lost when the process restarts (F2)
# - No distributed locking — concurrent processes each have their own store (F7)
# - F4 mitigation: email uniqueness is now checked before insert
#
# Thread safety
# -------------
# A threading.Lock guards every mutating operation so concurrent Streamlit
# threads / FastAPI async tasks within the same process are safe.
# =============================================================================

from __future__ import annotations

import threading
from copy import deepcopy
from datetime import date, datetime
from typing import Any, Optional


class InMemoryStore:
    """In-process key-value store that mirrors the PostgreSQL schema.

    Tables (all stored as dicts keyed by their primary ID):
        patients        — {patient_id: dict}
        doctors         — {doctor_id: dict}
        nurses          — {nurse_id: dict}
        slots           — {slot_id: dict}
        appointments    — {appointment_id: dict}
        triage_entries  — {triage_id: dict}
        roles_perms     — list[dict]   (seed data)
        audit_logs      — list[dict]   (append-only, Mongo fallback)

    Secondary indexes (for O(1) lookup by email/mobile/doctor+date):
        _patient_by_email   — {email: patient_id}
        _patient_by_mobile  — {mobile: patient_id}
        _doctor_by_email    — {email: doctor_id}
        _nurse_by_email     — {email: nurse_id}
        _slots_by_doctor_date — {(doctor_id, date_str): [slot_id, ...]}
        _apts_by_doctor_date  — {(doctor_id, date_str): [appointment_id, ...]}

    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reset()

    def _reset(self) -> None:
        """Clear all data — used by tests."""
        self.patients:       dict[str, dict] = {}
        self.doctors:        dict[str, dict] = {}
        self.nurses:         dict[str, dict] = {}
        self.slots:          dict[str, dict] = {}
        self.appointments:   dict[str, dict] = {}

        self.triage_entries: dict[str, dict] = {}
        self.roles_perms:    list[dict]      = []
        self.audit_logs:     list[dict]      = []

        # Secondary indexes
        self._patient_by_email:    dict[str, str] = {}
        self._patient_by_mobile:   dict[str, str] = {}
        self._patient_by_uhid:     dict[str, str] = {}
        self._doctor_by_email:     dict[str, str] = {}
        self._doctor_by_uhid:      dict[str, str] = {}
        self._nurse_by_email:      dict[str, str] = {}
        self._nurse_by_uhid:       dict[str, str] = {}
        self._slots_by_doctor_date:  dict[tuple, list[str]] = {}
        self._apts_by_doctor_date:   dict[tuple, list[str]] = {}


    # =========================================================================
    # PATIENTS
    # =========================================================================

    def upsert_patient(self, patient_dict: dict) -> dict:
        """Insert or update a patient record.

        ON CONFLICT (email): updates full_name and mobile (E1 mitigation).
        F4 mitigation: checks email uniqueness before inserting a new record.

        Returns the final stored record.
        """
        with self._lock:
            email = patient_dict["email"]
            pid   = patient_dict["patient_id"]
            # Check if this email already exists (F4 — duplicate guard)
            existing_id = self._patient_by_email.get(email)
            if existing_id and existing_id != pid:
                # Update the existing record (E1 — name update via upsert)
                existing = self.patients[existing_id]
                existing["full_name"] = patient_dict["full_name"]
                existing["mobile"]    = patient_dict["mobile"]
                if patient_dict.get("uhid"):
                    existing["uhid"] = patient_dict["uhid"]
                # Update mobile index
                old_mobile = existing.get("mobile")
                if old_mobile and old_mobile in self._patient_by_mobile:
                    del self._patient_by_mobile[old_mobile]
                self._patient_by_mobile[patient_dict["mobile"]] = existing_id
                if existing.get("uhid"):
                    self._patient_by_uhid[existing["uhid"]] = existing_id
                return deepcopy(existing)

            # New patient — store and index
            self.patients[pid] = deepcopy(patient_dict)
            self._patient_by_email[email] = pid
            self._patient_by_mobile[patient_dict["mobile"]] = pid
            if patient_dict.get("uhid"):
                self._patient_by_uhid[patient_dict["uhid"]] = pid
            return deepcopy(patient_dict)

    def update_patient_password(self, patient_id: str, password_hash: str, password_changed_at: str) -> bool:
        with self._lock:
            if patient_id not in self.patients:
                return False
            self.patients[patient_id]["password_hash"] = password_hash
            self.patients[patient_id]["password_changed_at"] = password_changed_at
            return True

    def get_patient_by_id(self, patient_id: str) -> Optional[dict]:
        with self._lock:
            rec = self.patients.get(patient_id)
            return deepcopy(rec) if rec else None

    def get_patient_by_email(self, email: str) -> Optional[dict]:
        with self._lock:
            pid = self._patient_by_email.get(email.lower())
            if pid:
                return deepcopy(self.patients[pid])
            return None

    def get_patient_by_uhid(self, uhid: str) -> Optional[dict]:
        with self._lock:
            pid = self._patient_by_uhid.get(uhid)
            if pid:
                return deepcopy(self.patients[pid])
            return None

    def get_patient_by_mobile(self, mobile: str) -> Optional[dict]:
        with self._lock:
            pid = self._patient_by_mobile.get(mobile)
            if pid:
                return deepcopy(self.patients[pid])
            return None

    def list_patients(self, active_only: bool = True) -> list[dict]:
        with self._lock:
            records = self.patients.values()
            if active_only:
                records = [r for r in records if r.get("is_active", True)]
            return [deepcopy(r) for r in records]

    def deactivate_patient(self, patient_id: str) -> bool:
        with self._lock:
            if patient_id in self.patients:
                self.patients[patient_id]["is_active"] = False
                return True
            return False

    # =========================================================================
    # DOCTORS
    # =========================================================================

    def upsert_doctor(self, doctor_dict: dict) -> dict:
        """Insert or update a doctor record (E7 — same email updates spec)."""
        with self._lock:
            email = doctor_dict["email"]
            did   = doctor_dict["doctor_id"]

            existing_id = self._doctor_by_email.get(email)
            if existing_id and existing_id != did:
                # Update existing record
                existing = self.doctors[existing_id]
                existing.update({
                    "full_name": doctor_dict["full_name"],
                    "mobile": doctor_dict["mobile"],
                    "specialization": doctor_dict["specialization"],
                    "max_patients_per_day": doctor_dict["max_patients_per_day"],
                    "work_start_time": doctor_dict["work_start_time"],
                    "work_end_time": doctor_dict["work_end_time"],
                    "consultation_duration_minutes": doctor_dict["consultation_duration_minutes"],
                    "is_active": doctor_dict.get("is_active", existing.get("is_active", True)),
                })
                if existing.get("uhid"):
                    self._doctor_by_uhid[existing["uhid"]] = existing_id
                return deepcopy(self.doctors[existing_id])

            self.doctors[did] = deepcopy(doctor_dict)
            self._doctor_by_email[email] = did
            if doctor_dict.get("uhid"):
                self._doctor_by_uhid[doctor_dict["uhid"]] = did
            return deepcopy(doctor_dict)

    def update_doctor_password(self, doctor_id: str, password_hash: str, password_changed_at: str) -> bool:
        with self._lock:
            if doctor_id not in self.doctors:
                return False
            self.doctors[doctor_id]["password_hash"] = password_hash
            self.doctors[doctor_id]["password_changed_at"] = password_changed_at
            return True

    def get_doctor_by_id(self, doctor_id: str) -> Optional[dict]:
        with self._lock:
            rec = self.doctors.get(doctor_id)
            return deepcopy(rec) if rec else None

    def get_doctor_by_email(self, email: str) -> Optional[dict]:
        with self._lock:
            did = self._doctor_by_email.get(email.lower())
            return deepcopy(self.doctors[did]) if did else None

    def get_doctor_by_uhid(self, uhid: str) -> Optional[dict]:
        with self._lock:
            did = self._doctor_by_uhid.get(uhid)
            return deepcopy(self.doctors[did]) if did else None

    def list_doctors(self, active_only: bool = True) -> list[dict]:
        with self._lock:
            records = self.doctors.values()
            if active_only:
                records = [r for r in records if r.get("is_active", True)]
            return [deepcopy(r) for r in records]

    # =========================================================================
    # NURSES
    # =========================================================================

    def upsert_nurse(self, nurse_dict: dict) -> dict:
        """Insert or update a nurse record."""
        with self._lock:
            email = nurse_dict["email"]
            nid   = nurse_dict["nurse_id"]

            existing_id = self._nurse_by_email.get(email)
            if existing_id and existing_id != nid:
                existing = self.nurses[existing_id]
                existing.update({
                    "full_name": nurse_dict["full_name"],
                    "mobile": nurse_dict["mobile"],
                })
                if existing.get("uhid"):
                    self._nurse_by_uhid[existing["uhid"]] = existing_id
                return deepcopy(self.nurses[existing_id])

            self.nurses[nid] = deepcopy(nurse_dict)
            self._nurse_by_email[email] = nid
            if nurse_dict.get("uhid"):
                self._nurse_by_uhid[nurse_dict["uhid"]] = nid
            return deepcopy(nurse_dict)

    def update_nurse_password(self, nurse_id: str, password_hash: str, password_changed_at: str) -> bool:
        with self._lock:
            if nurse_id not in self.nurses:
                return False
            self.nurses[nurse_id]["password_hash"] = password_hash
            self.nurses[nurse_id]["password_changed_at"] = password_changed_at
            return True

    def get_nurse_by_id(self, nurse_id: str) -> Optional[dict]:
        with self._lock:
            rec = self.nurses.get(nurse_id)
            return deepcopy(rec) if rec else None

    def get_nurse_by_email(self, email: str) -> Optional[dict]:
        with self._lock:
            nid = self._nurse_by_email.get(email.lower())
            return deepcopy(self.nurses[nid]) if nid else None

    def get_nurse_by_uhid(self, uhid: str) -> Optional[dict]:
        with self._lock:
            nid = self._nurse_by_uhid.get(uhid)
            return deepcopy(self.nurses[nid]) if nid else None

    def list_nurses(self, active_only: bool = True) -> list[dict]:
        with self._lock:
            records = self.nurses.values()
            if active_only:
                records = [r for r in records if r.get("is_active", True)]
            return [deepcopy(r) for r in records]

    # =========================================================================
    # SLOTS
    # =========================================================================

    def save_slots(self, slot_dicts: list[dict]) -> int:
        """Bulk-save a list of slot dicts. Returns count saved."""
        with self._lock:
            count = 0
            for s in slot_dicts:
                sid = s["slot_id"]
                self.slots[sid] = deepcopy(s)
                key = (s["doctor_id"], s["date"])
                self._slots_by_doctor_date.setdefault(key, []).append(sid)
                count += 1
            return count

    def get_slot(self, slot_id: str) -> Optional[dict]:
        with self._lock:
            rec = self.slots.get(slot_id)
            return deepcopy(rec) if rec else None

    def get_available_slots(self, doctor_id: str, date_str: str) -> list[dict]:
        """Return all bookable slots for a doctor on a date."""
        with self._lock:
            key = (doctor_id, date_str)
            ids = self._slots_by_doctor_date.get(key, [])
            result = []
            for sid in ids:
                s = self.slots.get(sid)
                if s and not s["is_booked"] and not s["is_blocked"] and not s["is_lunch_break"]:
                    result.append(deepcopy(s))
            result.sort(key=lambda x: x["start_time"])
            return result

    def get_all_slots_for_doctor_date(self, doctor_id: str, date_str: str) -> list[dict]:
        """Return all slots (including blocked/booked) for display."""
        with self._lock:
            key = (doctor_id, date_str)
            ids = self._slots_by_doctor_date.get(key, [])
            return [deepcopy(self.slots[sid]) for sid in ids if sid in self.slots]

    def update_slot_booked(self, slot_id: str, is_booked: bool) -> bool:
        """Flip is_booked flag — called on book / cancel / reschedule."""
        with self._lock:
            if slot_id in self.slots:
                self.slots[slot_id]["is_booked"] = is_booked
                return True
            return False

    def update_slot_blocked(self, slot_id: str, is_blocked: bool) -> bool:
        """Flip is_blocked flag for doctor-controlled schedule holds."""
        with self._lock:
            slot = self.slots.get(slot_id)
            if not slot:
                return False
            if slot.get("is_booked") and is_blocked:
                return False
            slot["is_blocked"] = is_blocked
            return True

    def has_slots_for_doctor_date(self, doctor_id: str, date_str: str) -> bool:
        """Check if any slots exist for a doctor on a date (for auto-generation check)."""
        with self._lock:
            key = (doctor_id, date_str)
            return bool(self._slots_by_doctor_date.get(key))

    def find_next_available_slot(
        self, doctor_id: str, after_date_str: str, max_days: int = 14
    ) -> Optional[dict]:
        """Find the earliest available slot after a given date (E10)."""
        with self._lock:
            from datetime import date as date_type, timedelta
            start = date_type.fromisoformat(after_date_str) + timedelta(days=1)
            for i in range(max_days):
                d = start + timedelta(days=i)
                # Skip weekends (E12 mitigation)
                if d.weekday() in (5, 6):
                    continue
                key = (doctor_id, d.isoformat())
                ids = self._slots_by_doctor_date.get(key, [])
                for sid in sorted(ids):
                    s = self.slots.get(sid)
                    if s and not s["is_booked"] and not s["is_blocked"] and not s["is_lunch_break"]:
                        return deepcopy(s)
            return None

    # =========================================================================
    # APPOINTMENTS
    # =========================================================================

    def save_appointment(self, apt_dict: dict) -> dict:
        with self._lock:
            aid = apt_dict["appointment_id"]
            self.appointments[aid] = deepcopy(apt_dict)
            key = (apt_dict["doctor_id"], apt_dict["date"])
            self._apts_by_doctor_date.setdefault(key, []).append(aid)
            return deepcopy(apt_dict)

    def update_appointment(self, apt_dict: dict) -> dict:
        """Full replace of an appointment record (status changes, reschedules)."""
        with self._lock:
            aid = apt_dict["appointment_id"]
            if aid not in self.appointments:
                raise KeyError(f"Appointment {aid} not found.")
            previous = self.appointments[aid]
            old_key = (previous["doctor_id"], previous["date"])
            new_key = (apt_dict["doctor_id"], apt_dict["date"])
            if old_key != new_key:
                old_ids = self._apts_by_doctor_date.get(old_key, [])
                self._apts_by_doctor_date[old_key] = [item for item in old_ids if item != aid]
                self._apts_by_doctor_date.setdefault(new_key, []).append(aid)
            self.appointments[aid] = deepcopy(apt_dict)
            return deepcopy(apt_dict)

    def get_appointment(self, appointment_id: str) -> Optional[dict]:
        with self._lock:
            rec = self.appointments.get(appointment_id)
            return deepcopy(rec) if rec else None

    def get_appointments_for_patient(self, patient_id: str) -> list[dict]:
        with self._lock:
            return [
                deepcopy(a) for a in self.appointments.values()
                if a["patient_id"] == patient_id
            ]

    def get_appointments_for_doctor_date(
        self, doctor_id: str, date_str: str, status_filter: list[str] | None = None
    ) -> list[dict]:
        with self._lock:
            key = (doctor_id, date_str)
            ids = self._apts_by_doctor_date.get(key, [])
            result = []
            for aid in ids:
                a = self.appointments.get(aid)
                if not a:
                    continue
                if status_filter and a["status"] not in status_filter:
                    continue
                result.append(deepcopy(a))
            result.sort(key=lambda x: x["start_time"])
            return result

    def assign_nurse_to_appointment(self, appointment_id: str, nurse_id: str) -> Optional[dict]:
        with self._lock:
            rec = self.appointments.get(appointment_id)
            if not rec:
                return None
            rec["assigned_nurse_id"] = nurse_id
            return deepcopy(rec)

    def get_appointments_for_date(self, date_str: str, status_filter: list[str] | None = None) -> list[dict]:
        with self._lock:
            result = []
            for a in self.appointments.values():
                if a.get("date") != date_str:
                    continue
                if status_filter and a.get("status") not in status_filter:
                    continue
                result.append(deepcopy(a))
            result.sort(key=lambda x: x.get("start_time", ""))
            return result

    def count_booked_appointments(self, doctor_id: str, date_str: str) -> int:
        """Count active (booked) appointments for a doctor/date (NF6 in GO4)."""
        with self._lock:
            key = (doctor_id, date_str)
            ids = self._apts_by_doctor_date.get(key, [])
            return sum(
                1 for aid in ids
                if self.appointments.get(aid, {}).get("status") == "booked"
            )

    def check_slot_conflict(self, slot_id: str) -> bool:
        """Return True if slot is already booked by any active appointment."""
        with self._lock:
            for a in self.appointments.values():
                if a["slot_id"] == slot_id and a["status"] not in ("cancelled", "completed", "no-show"):
                    return True
            return False

    def get_all_appointments(
        self,
        date_str: str | None = None,
        doctor_id: str | None = None,
        status_filter: list[str] | None = None,
    ) -> list[dict]:
        """Flexible list for reporting (GO8)."""
        with self._lock:
            result = []
            for a in self.appointments.values():
                if date_str and a["date"] != date_str:
                    continue
                if doctor_id and a["doctor_id"] != doctor_id:
                    continue
                if status_filter and a["status"] not in status_filter:
                    continue
                result.append(deepcopy(a))
            return result



    # =========================================================================
    # TRIAGE
    # =========================================================================

    def save_triage(self, triage_dict: dict) -> dict:
        with self._lock:
            tid = triage_dict["triage_id"]
            self.triage_entries[tid] = deepcopy(triage_dict)
            return deepcopy(triage_dict)

    def get_triage_for_patient(self, patient_id: str) -> list[dict]:
        with self._lock:
            return [
                deepcopy(t) for t in self.triage_entries.values()
                if t["patient_id"] == patient_id
            ]

    def get_triage_for_date(self, date_str: str, doctor_id: str | None = None) -> list[dict]:
        with self._lock:
            result = []
            for t in self.triage_entries.values():
                if t["date"] != date_str:
                    continue
                if doctor_id and t["doctor_id"] != doctor_id:
                    continue
                result.append(deepcopy(t))
            return result

    # =========================================================================
    # ROLES & PERMISSIONS
    # =========================================================================

    def get_roles_permissions(self, role_name: str | None = None) -> list[dict]:
        with self._lock:
            if role_name:
                return [deepcopy(r) for r in self.roles_perms if r.get("role_name") == role_name]
            return [deepcopy(r) for r in self.roles_perms]

    # =========================================================================
    # AUDIT LOG (Mongo fallback — append only)
    # =========================================================================

    def log_audit(self, event: str, data: dict, actor: str | None = None) -> None:
        """Append an audit entry (used when MongoDB is unavailable)."""
        with self._lock:
            self.audit_logs.append({
                "event":     event,
                "actor":     actor,
                "data":      deepcopy(data),
                "logged_at": datetime.now().isoformat(),
            })

    def get_audit_logs(self, event_filter: str | None = None) -> list[dict]:
        with self._lock:
            if event_filter:
                return [deepcopy(l) for l in self.audit_logs if l["event"] == event_filter]
            return [deepcopy(l) for l in self.audit_logs]

    # =========================================================================
    # REPORTING helpers (GO8)
    # =========================================================================

    def get_report_data(self, date_str: str, doctor_id: str | None = None) -> dict:
        """Aggregate all metrics needed for the daily report (GO8 LO2)."""
        apts = self.get_all_appointments(date_str=date_str, doctor_id=doctor_id)
        total     = len(apts)
        completed = sum(1 for a in apts if a["status"] == "completed")
        cancelled = sum(1 for a in apts if a["status"] == "cancelled")
        no_show   = sum(1 for a in apts if a["status"] == "no-show")

        # Busiest doctor (NF5)
        doctor_counts: dict[str, int] = {}
        for a in apts:
            if a["status"] == "completed":
                doctor_counts[a["doctor_id"]] = doctor_counts.get(a["doctor_id"], 0) + 1
        busiest_doctor_id = max(doctor_counts, key=doctor_counts.get) if doctor_counts else None

        # Peak booking hour (NF6)
        hour_counts: dict[int, int] = {}
        for a in apts:
            hour = int(a["start_time"].split(":")[0])
            hour_counts[hour] = hour_counts.get(hour, 0) + 1
        peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else None

        # Total slots generated for the day
        all_slots = [
            s for s in self.slots.values()
            if s["date"] == date_str and not s["is_blocked"]
        ]
        total_slots = len(all_slots)

        return {
            "date":              date_str,
            "doctor_id_filter":  doctor_id,
            "total_appointments": total,
            "total_completed":    completed,
            "total_cancelled":    cancelled,
            "total_no_shows":     no_show,
            "busiest_doctor_id":  busiest_doctor_id,
            "peak_hour":          peak_hour,
            "slot_utilization_pct": round((completed / total_slots * 100), 1) if total_slots else 0,
            "cancellation_rate_pct": round((cancelled / total * 100), 1) if total else 0,
        }

    # =========================================================================
    # Misc
    # =========================================================================

    @property
    def is_connected(self) -> bool:
        """Always True — in-memory store is always available."""
        return True

    def __repr__(self) -> str:
        return (
            f"InMemoryStore("
            f"patients={len(self.patients)}, "
            f"doctors={len(self.doctors)}, "
            f"nurses={len(self.nurses)}, "
            f"slots={len(self.slots)}, "
            f"appointments={len(self.appointments)}, "
            f"triage={len(self.triage_entries)})"
        )
