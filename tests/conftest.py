# =============================================================================
# tests/conftest.py
# Shared pytest fixtures — InMemoryStore-backed, no real DB needed
# =============================================================================

from __future__ import annotations

import sys
import os
from datetime import date, time, timedelta

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from features.shared.database.in_memory import InMemoryStore
from features.shared.database.mongo     import MongoManager
from features.shared.services.booking_service  import BookingService
from features.shared.services.schedule_manager import ScheduleManager
from features.shared.services.queue_manager    import QueueManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def in_memory_store():
    """Fresh in-memory data store for each test."""
    store = InMemoryStore()
    return store


@pytest.fixture
def mongo_manager():
    """MongoManager that falls back to in-memory (no real Mongo needed)."""
    return MongoManager(config={"uri": "mongodb://localhost:27017/test_db_fake"})


@pytest.fixture
def schedule_manager(in_memory_store):
    """ScheduleManager wired to in-memory store."""
    return ScheduleManager(db=in_memory_store)


@pytest.fixture
def queue_manager(in_memory_store, mongo_manager):
    """QueueManager wired to in-memory backends."""
    return QueueManager(db=in_memory_store, mongo=mongo_manager)


@pytest.fixture
def booking_service(in_memory_store, mongo_manager, schedule_manager, queue_manager):
    """BookingService wired to all in-memory backends."""
    return BookingService(
        db=in_memory_store,
        mongo=mongo_manager,
        schedule=schedule_manager,
        queue=queue_manager,
    )


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_patient_data():
    """Minimal valid patient registration data."""
    return {
        "full_name": "Riya Sharma",
        "email": "riya.sharma@example.com",
        "mobile": "9876543210",
        "date_of_birth": date(1995, 6, 15),
        "gender": "Female",
        "blood_group": "O+",
        "address": "42 MG Road, Bangalore",
    }


@pytest.fixture
def sample_doctor_data():
    """Minimal valid doctor registration data."""
    return {
        "full_name": "Dr Priya Nair",
        "email": "priya.nair@hospital.com",
        "mobile": "9988776655",
        "specialization": "Cardiologist",
        "max_patients_per_day": 20,
    }


@pytest.fixture
def future_weekday():
    """Return the next weekday that is at least 1 day in the future."""
    d = date.today() + timedelta(days=1)
    while d.weekday() in (5, 6):   # skip weekends
        d += timedelta(days=1)
    return d


@pytest.fixture
def registered_patient(booking_service, sample_patient_data):
    """Register and return the patient dict."""
    return booking_service.register_patient(**sample_patient_data)


@pytest.fixture
def registered_doctor(booking_service, sample_doctor_data):
    """Register and return the doctor dict."""
    return booking_service.register_doctor(**sample_doctor_data)


@pytest.fixture
def sample_nurse_data():
    """Minimal valid nurse registration data."""
    return {
        "full_name": "Anjali Kumar",
        "email": "anjali.kumar@hospital.com",
        "mobile": "9876512345",
    }


@pytest.fixture
def registered_nurse(booking_service, sample_nurse_data):
    """Register and return the nurse dict."""
    return booking_service.register_nurse(**sample_nurse_data)


@pytest.fixture
def doctor_with_slots(booking_service, registered_doctor, future_weekday):
    """Doctor with auto-generated slots (created during registration).

    register_doctor() now auto-generates availability + slots for
    the next N weekdays based on the doctor's specialization config.
    This fixture just verifies slots exist and returns the doctor.
    """
    # Slots are auto-generated during registration — just verify
    slots = booking_service.get_available_slots(
        registered_doctor["doctor_id"], future_weekday
    )
    assert len(slots) > 0, (
        f"Expected auto-generated slots for {registered_doctor['doctor_id']} on {future_weekday}"
    )
    return registered_doctor


@pytest.fixture
def available_slot(booking_service, doctor_with_slots, future_weekday):
    """Return the first available slot for the doctor on future_weekday."""
    slots = booking_service.get_available_slots(
        doctor_with_slots["doctor_id"], future_weekday
    )
    assert len(slots) > 0, "Expected at least one available slot"
    return slots[0]

