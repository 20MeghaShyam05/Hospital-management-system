# =============================================================================
# tests/test_api.py
# FastAPI endpoint tests using TestClient
# — tests the full HTTP layer: request validation, status codes, response shape
# =============================================================================

from __future__ import annotations

import sys
import os
from datetime import date, time, timedelta

import pytest
from fastapi.testclient import TestClient

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from features.shared.database.in_memory import InMemoryStore
from features.shared.database.mongo import MongoManager
from features.shared.services.booking_service import BookingService
from features.shared.services.schedule_manager import ScheduleManager
from features.shared.services.queue_manager import QueueManager
from features.shared.services.auth_service import AuthService
from features.core.app import app
from features.core.dependencies import app_state


# ---------------------------------------------------------------------------
# Fixtures — wire up TestClient with in-memory backends
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def wire_test_services():
    """Replace app_state with fresh in-memory services for every test."""
    store = InMemoryStore()
    mongo = MongoManager(config={"uri": "mongodb://localhost:27017/fake"})

    app_state.db       = store
    app_state.mongo    = mongo
    app_state.schedule = ScheduleManager(db=store)
    app_state.queue_mgr = QueueManager(db=store, mongo=mongo)
    app_state.booking  = BookingService(
        db=store,
        mongo=mongo,
        schedule=app_state.schedule,
        queue=app_state.queue_mgr,
    )
    app_state.auth = AuthService(db=store)
    yield


@pytest.fixture
def client():
    """FastAPI TestClient (sync) — shares the wired services."""
    return TestClient(app, raise_server_exceptions=False)


def _future_weekday() -> date:
    d = date.today() + timedelta(days=1)
    while d.weekday() in (5, 6):
        d += timedelta(days=1)
    return d


def _far_future_weekday() -> date:
    """A weekday far enough that auto-generation (7 days) hasn't covered it."""
    d = date.today() + timedelta(days=20)
    while d.weekday() in (5, 6):
        d += timedelta(days=1)
    return d


def _find_saturday() -> date:
    d = date.today()
    while d.weekday() != 5:
        d += timedelta(days=1)
    return d


# ---------------------------------------------------------------------------
# Helpers — register entities via API
# ---------------------------------------------------------------------------

def _register_patient(client, **overrides):
    data = {
        "full_name": "Test Patient",
        "email": "patient@test.com",
        "mobile": "9876543210",
    }
    data.update(overrides)
    resp = client.post("/patients", json=data)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _register_doctor(client, **overrides):
    data = {
        "full_name": "Dr Test Doc",
        "email": "doctor@test.com",
        "mobile": "9988776655",
        "specialization": "General Physician",
        "max_patients_per_day": 20,
    }
    data.update(overrides)
    resp = client.post("/doctors", json=data)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _register_nurse(client, **overrides):
    data = {
        "full_name": "Test Nurse",
        "email": "nurse@test.com",
        "mobile": "9876512345",
    }
    data.update(overrides)
    resp = client.post("/nurses", json=data)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _get_slots(client, doctor_id, for_date=None):
    d = for_date or _future_weekday()
    resp = client.get(f"/slots/{doctor_id}/{d.isoformat()}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _book_appointment(client, patient_id, doctor_id, slot_id, for_date=None, priority="normal"):
    d = for_date or _future_weekday()
    resp = client.post("/appointments", json={
        "patient_id": patient_id,
        "doctor_id": doctor_id,
        "slot_id": slot_id,
        "date": d.isoformat(),
        "notes": "API test booking",
        "priority": priority,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def _login(client, identifier, password, role):
    resp = client.post("/auth/login", json={
        "identifier": identifier,
        "password": password,
        "role": role,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


# =========================================================================
# GO1 — Patient endpoints
# =========================================================================

class TestPatientAPI:

    def test_register_patient(self, client):
        result = _register_patient(client)
        assert "patient_id" in result
        assert result["uhid"].startswith("HMS-PAT-")
        assert result["full_name"] == "Test Patient"

    def test_register_patient_invalid_mobile(self, client):
        resp = client.post("/patients", json={
            "full_name": "Bad Mobile",
            "email": "bad@test.com",
            "mobile": "12345",   # too short + wrong start
        })
        assert resp.status_code == 422

    def test_register_patient_invalid_name(self, client):
        resp = client.post("/patients", json={
            "full_name": "AB",   # too short
            "email": "ab@test.com",
            "mobile": "9876543210",
        })
        assert resp.status_code == 422

    def test_list_patients(self, client):
        _register_patient(client)
        resp = client.get("/patients")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_patient_by_id(self, client):
        patient = _register_patient(client)
        resp = client.get(f"/patients/{patient['patient_id']}")
        assert resp.status_code == 200
        assert resp.json()["email"] == "patient@test.com"

    def test_get_patient_by_uhid(self, client):
        patient = _register_patient(client)
        resp = client.get(f"/patients/{patient['uhid']}")
        assert resp.status_code == 200
        assert resp.json()["patient_id"] == patient["patient_id"]

    def test_get_patient_not_found(self, client):
        resp = client.get("/patients/nonexistent-id")
        assert resp.status_code == 404


# =========================================================================
# GO2 — Doctor endpoints
# =========================================================================

class TestDoctorAPI:

    def test_register_doctor(self, client):
        result = _register_doctor(client)
        assert "doctor_id" in result
        assert result["uhid"].startswith("HMS-DOC-")
        assert result["specialization"] == "General Physician"

    def test_register_doctor_with_custom_hours(self, client):
        result = _register_doctor(client,
            email="custom@hosp.com",
            work_start_time="10:00:00",
            work_end_time="14:00:00",
            consultation_duration_minutes=20,
        )
        assert result["work_start_time"] == "10:00:00"
        assert result["work_end_time"] == "14:00:00"
        assert result["consultation_duration_minutes"] == 20

    def test_register_doctor_specialization_defaults(self, client):
        """Cardiologist should get 20-min consultation and 09:00-16:00 hours."""
        result = _register_doctor(client,
            email="cardio@hosp.com",
            specialization="Cardiologist",
        )
        assert result["consultation_duration_minutes"] == 20
        assert result["work_start_time"] == "09:00:00"
        assert result["work_end_time"] == "16:00:00"

    def test_register_doctor_auto_generates_slots(self, client):
        """Registration should auto-create slots for the next future weekday."""
        doctor = _register_doctor(client)
        fw = _future_weekday()
        slots = _get_slots(client, doctor["doctor_id"], fw)
        assert len(slots) > 0, "Expected auto-generated slots after registration"

    def test_register_doctor_invalid_specialization(self, client):
        resp = client.post("/doctors", json={
            "full_name": "Dr Bad Spec",
            "email": "bad@hosp.com",
            "mobile": "9988776655",
            "specialization": "Astrologer",   # not in enum
        })
        assert resp.status_code == 422

    def test_register_doctor_rejects_removed_department_field(self, client):
        resp = client.post("/doctors", json={
            "full_name": "Dr Legacy Field",
            "email": "legacy@hosp.com",
            "mobile": "9988776644",
            "specialization": "General Physician",
            "department": "General",
        })
        assert resp.status_code == 422

    def test_list_doctors(self, client):
        _register_doctor(client)
        resp = client.get("/doctors")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_doctor_by_id(self, client):
        doctor = _register_doctor(client)
        resp = client.get(f"/doctors/{doctor['doctor_id']}")
        assert resp.status_code == 200

    def test_get_doctor_by_uhid(self, client):
        doctor = _register_doctor(client)
        resp = client.get(f"/doctors/{doctor['uhid']}")
        assert resp.status_code == 200
        assert resp.json()["doctor_id"] == doctor["doctor_id"]

    def test_get_doctor_not_found(self, client):
        resp = client.get("/doctors/nonexistent-id")
        assert resp.status_code == 404


# =========================================================================
# Nurse API
# =========================================================================

class TestNurseAPI:

    def test_register_nurse(self, client):
        result = _register_nurse(client)
        assert "nurse_id" in result
        assert result["full_name"] == "Test Nurse"

    def test_list_nurses(self, client):
        _register_nurse(client)
        resp = client.get("/nurses")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_nurse_by_id(self, client):
        nurse = _register_nurse(client)
        resp = client.get(f"/nurses/{nurse['nurse_id']}")
        assert resp.status_code == 200
        assert resp.json()["full_name"] == "Test Nurse"

    def test_get_nurse_not_found(self, client):
        resp = client.get("/nurses/nonexistent-id")
        assert resp.status_code == 404


# =========================================================================
# Triage API
# =========================================================================

class TestTriageAPI:

    def test_create_triage(self, client):
        patient = _register_patient(client)
        nurse = _register_nurse(client)
        doctor = _register_doctor(client)
        fw = _future_weekday()
        resp = client.post("/triage", json={
            "patient_id": patient["patient_id"],
            "nurse_id": nurse["nurse_id"],
            "doctor_id": doctor["doctor_id"],
            "date": fw.isoformat(),
            "queue_type": "normal",
            "blood_pressure": "120/80",
            "heart_rate": 72,
            "temperature": 37.0,
        })
        assert resp.status_code == 201
        assert resp.json()["triage_id"]
        assert resp.json()["queue_type"] == "normal"

    def test_get_triage_by_date(self, client):
        patient = _register_patient(client)
        nurse = _register_nurse(client)
        doctor = _register_doctor(client)
        fw = _future_weekday()
        client.post("/triage", json={
            "patient_id": patient["patient_id"],
            "nurse_id": nurse["nurse_id"],
            "doctor_id": doctor["doctor_id"],
            "date": fw.isoformat(),
            "queue_type": "normal",
        })
        resp = client.get(f"/triage/date/{fw.isoformat()}")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


# =========================================================================
# GO3 — Slots (auto-generated)
# =========================================================================

class TestSlotsAPI:

    def test_auto_generated_slots_exist(self, client):
        """Doctor registration auto-generates slots, no manual action needed."""
        doctor = _register_doctor(client)
        slots = _get_slots(client, doctor["doctor_id"], _future_weekday())
        assert len(slots) > 0
        for s in slots:
            assert s["is_lunch_break"] is False
            assert s["is_booked"] is False

    def test_on_demand_slot_generation(self, client):
        """Requesting slots for a far future weekday should auto-generate them."""
        doctor = _register_doctor(client)
        far_d = _far_future_weekday()
        slots = _get_slots(client, doctor["doctor_id"], far_d)
        assert len(slots) > 0, "On-demand slot generation should create slots"

    def test_different_specializations_different_slot_counts(self, client):
        """GP (10 min) and Psychiatrist (30 min) should have different slot counts."""
        gp = _register_doctor(client, specialization="General Physician", email="gp@hosp.com")
        psych = _register_doctor(client, specialization="Psychiatrist", email="psych@hosp.com")
        fw = _future_weekday()
        gp_slots = _get_slots(client, gp["doctor_id"], fw)
        psych_slots = _get_slots(client, psych["doctor_id"], fw)
        assert len(gp_slots) > len(psych_slots), (
            f"GP should have more slots ({len(gp_slots)}) than Psychiatrist ({len(psych_slots)})"
        )


# =========================================================================
# GO4 — Book Appointment (uses auto-generated slots)
# =========================================================================

class TestBookAppointmentAPI:

    def test_book_appointment_success(self, client):
        patient = _register_patient(client)
        doctor  = _register_doctor(client)
        # Slots auto-generated on registration — just fetch them
        slots = _get_slots(client, doctor["doctor_id"])
        result = _book_appointment(client, patient["patient_id"], doctor["doctor_id"], slots[0]["slot_id"])
        assert result["status"] == "booked"
        assert result["queue_position"] >= 1

    def test_book_appointment_using_uhids(self, client):
        patient = _register_patient(client)
        doctor  = _register_doctor(client)
        slots = _get_slots(client, doctor["uhid"])
        result = _book_appointment(client, patient["uhid"], doctor["uhid"], slots[0]["slot_id"])
        assert result["status"] == "booked"

    def test_book_past_date_rejected(self, client):
        patient = _register_patient(client)
        doctor  = _register_doctor(client)
        slots = _get_slots(client, doctor["doctor_id"])
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        resp = client.post("/appointments", json={
            "patient_id": patient["patient_id"],
            "doctor_id": doctor["doctor_id"],
            "slot_id": slots[0]["slot_id"],
            "date": yesterday,
        })
        assert resp.status_code == 422

    def test_book_weekend_rejected(self, client):
        patient = _register_patient(client)
        doctor  = _register_doctor(client)
        slots = _get_slots(client, doctor["doctor_id"])
        saturday = _find_saturday().isoformat()
        resp = client.post("/appointments", json={
            "patient_id": patient["patient_id"],
            "doctor_id": doctor["doctor_id"],
            "slot_id": slots[0]["slot_id"],
            "date": saturday,
        })
        assert resp.status_code == 422

    def test_book_nonexistent_patient(self, client):
        doctor = _register_doctor(client)
        slots = _get_slots(client, doctor["doctor_id"])
        resp = client.post("/appointments", json={
            "patient_id": "fake-patient",
            "doctor_id": doctor["doctor_id"],
            "slot_id": slots[0]["slot_id"],
            "date": _future_weekday().isoformat(),
        })
        assert resp.status_code == 422

    def test_book_slot_for_wrong_doctor_rejected(self, client):
        patient = _register_patient(client)
        doctor_one = _register_doctor(client, email="doc-one@hosp.com")
        doctor_two = _register_doctor(client, email="doc-two@hosp.com", mobile="9988776656")
        slots = _get_slots(client, doctor_one["doctor_id"])
        resp = client.post("/appointments", json={
            "patient_id": patient["patient_id"],
            "doctor_id": doctor_two["doctor_id"],
            "slot_id": slots[0]["slot_id"],
            "date": _future_weekday().isoformat(),
        })
        assert resp.status_code == 422

    def test_get_appointment(self, client):
        patient = _register_patient(client)
        doctor  = _register_doctor(client)
        slots = _get_slots(client, doctor["doctor_id"])
        booked = _book_appointment(client, patient["patient_id"], doctor["doctor_id"], slots[0]["slot_id"])
        resp = client.get(f"/appointments/{booked['appointment_id']}")
        assert resp.status_code == 200
        assert resp.json()["appointment_id"] == booked["appointment_id"]

    def test_get_patient_appointments(self, client):
        patient = _register_patient(client)
        doctor  = _register_doctor(client)
        slots = _get_slots(client, doctor["doctor_id"])
        _book_appointment(client, patient["patient_id"], doctor["doctor_id"], slots[0]["slot_id"])
        resp = client.get(f"/appointments/patient/{patient['patient_id']}")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_book_emergency_appointment_persists_priority(self, client):
        patient = _register_patient(client)
        doctor = _register_doctor(client)
        slots = _get_slots(client, doctor["doctor_id"])
        result = _book_appointment(
            client,
            patient["patient_id"],
            doctor["doctor_id"],
            slots[0]["slot_id"],
            priority="emergency",
        )
        assert result["priority"] == "emergency"


# =========================================================================
# GO5 — Cancel Appointment
# =========================================================================

class TestCancelAppointmentAPI:

    def test_cancel_success(self, client):
        patient = _register_patient(client)
        doctor  = _register_doctor(client)
        slots = _get_slots(client, doctor["doctor_id"])
        booked = _book_appointment(client, patient["patient_id"], doctor["doctor_id"], slots[0]["slot_id"])

        resp = client.post(f"/appointments/{booked['appointment_id']}/cancel", json={
            "reason": "Family emergency, need to travel",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_cancel_short_reason_rejected(self, client):
        patient = _register_patient(client)
        doctor  = _register_doctor(client)
        slots = _get_slots(client, doctor["doctor_id"])
        booked = _book_appointment(client, patient["patient_id"], doctor["doctor_id"], slots[0]["slot_id"])

        resp = client.post(f"/appointments/{booked['appointment_id']}/cancel", json={
            "reason": "short",
        })
        assert resp.status_code == 422


# =========================================================================
# GO6 — Reschedule Appointment
# =========================================================================

class TestRescheduleAppointmentAPI:

    def test_reschedule_success(self, client):
        patient = _register_patient(client)
        doctor  = _register_doctor(client)
        fw = _future_weekday()
        # Slots already auto-generated
        slots = _get_slots(client, doctor["doctor_id"], fw)
        booked = _book_appointment(client, patient["patient_id"], doctor["doctor_id"], slots[0]["slot_id"], fw)

        resp = client.post(f"/appointments/{booked['appointment_id']}/reschedule", json={
            "new_slot_id": slots[1]["slot_id"],
            "new_date": fw.isoformat(),
        })
        assert resp.status_code == 200
        assert resp.json()["slot_id"] == slots[1]["slot_id"]
        assert resp.json()["reschedule_count"] == 1

    def test_reschedule_slot_date_mismatch_rejected(self, client):
        patient = _register_patient(client)
        doctor  = _register_doctor(client)
        fw = _future_weekday()
        slots = _get_slots(client, doctor["doctor_id"], fw)
        booked = _book_appointment(client, patient["patient_id"], doctor["doctor_id"], slots[0]["slot_id"], fw)
        next_day = fw + timedelta(days=1)
        while next_day.weekday() in (5, 6):
            next_day += timedelta(days=1)
        resp = client.post(f"/appointments/{booked['appointment_id']}/reschedule", json={
            "new_slot_id": slots[1]["slot_id"],
            "new_date": next_day.isoformat(),
        })
        assert resp.status_code == 422


# =========================================================================
# GO7 — Queue
# =========================================================================

class TestQueueAPI:

    def _setup_booked(self, client):
        patient = _register_patient(client)
        doctor  = _register_doctor(client)
        fw = _future_weekday()
        slots = _get_slots(client, doctor["doctor_id"], fw)
        booked = _book_appointment(client, patient["patient_id"], doctor["doctor_id"], slots[0]["slot_id"], fw)
        return patient, doctor, booked, fw

    def test_get_queue(self, client):
        _, doctor, _, fw = self._setup_booked(client)
        resp = client.get(f"/queue/{doctor['doctor_id']}/{fw.isoformat()}")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_get_queue_summary(self, client):
        _, doctor, _, fw = self._setup_booked(client)
        resp = client.get(f"/queue/{doctor['doctor_id']}/{fw.isoformat()}/summary")
        assert resp.status_code == 200
        summary = resp.json()
        assert summary["total"] >= 1


# =========================================================================
# GO8 — Report
# =========================================================================

class TestReportAPI:

    def test_report_empty_date(self, client):
        resp = client.get(f"/reports/{date.today().isoformat()}")
        assert resp.status_code == 200
        report = resp.json()
        assert report["total_appointments"] == 0

    def test_report_future_date_rejected(self, client):
        future = (date.today() + timedelta(days=30)).isoformat()
        resp = client.get(f"/reports/{future}")
        assert resp.status_code == 422


# =========================================================================
# Health check
# =========================================================================

class TestHealthCheck:

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestAuthAPI:

    def test_admin_login_and_change_password_rejected(self, client):
        login = _login(client, "admin", "admin123", "admin")
        token = login["access_token"]
        change = client.post(
            "/auth/change-password",
            json={"current_password": "admin123", "new_password": "admin12345"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert change.status_code == 403

    def test_patient_login_with_initial_password_and_change_password(self, client):
        patient = _register_patient(client, email="authpatient@test.com", mobile="9876543211")
        login = _login(client, patient["uhid"], "9876543211", "patient")
        token = login["access_token"]

        change = client.post(
            "/auth/change-password",
            json={"current_password": "9876543211", "new_password": "patientpass1"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert change.status_code == 200

        relogin = client.post("/auth/login", json={
            "identifier": patient["uhid"],
            "password": "patientpass1",
            "role": "patient",
        })
        assert relogin.status_code == 200

    def test_nurse_login(self, client):
        nurse = _register_nurse(client, email="authnurse@test.com", mobile="9876598765")
        login = _login(client, nurse["nurse_id"], "9876598765", "nurse")
        assert login["access_token"]
        assert login["user"]["role"] == "nurse"


# =========================================================================
# Full booking flow — end-to-end (with auto-generated slots)
# =========================================================================

class TestFullBookingFlow:

    def test_end_to_end_flow(self, client):
        """Complete flow: register → (auto-generated slots) → book → cancel."""
        # 1. Register patient
        patient = _register_patient(client)
        assert patient["patient_id"]

        # 2. Register doctor (auto-generates slots for upcoming weekdays)
        doctor = _register_doctor(client)
        assert doctor["doctor_id"]
        assert doctor["consultation_duration_minutes"] == 10  # GP default

        # 3. Slots are auto-generated! Just verify.
        fw = _future_weekday()
        slots = _get_slots(client, doctor["doctor_id"], fw)
        assert len(slots) > 0, "Expected auto-generated slots after registration"

        # 4. Book appointment
        booked = _book_appointment(client, patient["patient_id"], doctor["doctor_id"], slots[0]["slot_id"], fw)
        assert booked["status"] == "booked"

        # 5. Verify appointment is retrievable
        resp = client.get(f"/appointments/{booked['appointment_id']}")
        assert resp.status_code == 200

        # 6. Check queue
        resp = client.get(f"/queue/{doctor['doctor_id']}/{fw.isoformat()}")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

        # 7. Cancel appointment
        resp = client.post(f"/appointments/{booked['appointment_id']}/cancel", json={
            "reason": "Complete flow test — cancelling appointment",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

        # 8. Slot should be released
        slots_after = _get_slots(client, doctor["doctor_id"], fw)
        slot_ids_after = [s["slot_id"] for s in slots_after]
        assert slots[0]["slot_id"] in slot_ids_after
