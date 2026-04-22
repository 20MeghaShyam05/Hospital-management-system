# =============================================================================
# tests/test_models.py
# Unit tests for all domain models — Person, Patient, Doctor, Appointment,
# AppointmentSlot, Nurse, Triage, AppointmentQueue
# =============================================================================

from __future__ import annotations

import pytest
from datetime import date, time, timedelta

from features.shared.models.person import Person, validate_email, validate_mobile
from features.shared.models.patient import Patient, Gender, BloodGroup
from features.shared.models.doctor import Doctor, Specialization
from features.shared.models.appointment import Appointment, AppointmentStatus, AppointmentPriority
from features.shared.models.slot import (
    TimeSlot, AppointmentSlot, generate_slots_for_doctor,
    LUNCH_START, LUNCH_END, SLOT_DURATION_OPTIONS,
)
from features.shared.models.queue import AppointmentQueue, QueueStatus, TriageGroup
from features.shared.models.nurse import Nurse
from features.shared.models.triage import Triage, QueueType


# =========================================================================
# Person (base class) validation
# =========================================================================

class TestPerson:

    def test_valid_person(self):
        p = Person(full_name="John Doe", email="john@example.com", mobile="9876543210")
        assert p.full_name == "John Doe"
        assert p.email == "john@example.com"
        assert p.mobile == "9876543210"
        assert p.is_active is True

    def test_name_too_short(self):
        with pytest.raises(ValueError, match="min 3 characters"):
            Person(full_name="JD", email="j@e.com", mobile="9876543210")

    def test_invalid_email_format(self):
        with pytest.raises(ValueError, match="Invalid email"):
            Person(full_name="John Doe", email="not-an-email", mobile="9876543210")

    def test_email_normalised_lowercase(self):
        p = Person(full_name="John Doe", email="John@Example.COM", mobile="9876543210")
        assert p.email == "john@example.com"

    def test_invalid_mobile_too_short(self):
        with pytest.raises(ValueError, match="10-digit"):
            Person(full_name="John Doe", email="john@example.com", mobile="12345")

    def test_invalid_mobile_wrong_start(self):
        with pytest.raises(ValueError, match="starting with 6-9"):
            Person(full_name="John Doe", email="john@example.com", mobile="1234567890")

    def test_mobile_strips_hyphens(self):
        p = Person(full_name="John Doe", email="john@example.com", mobile="98765-43210")
        assert p.mobile == "9876543210"

    def test_deactivate_activate(self):
        p = Person(full_name="John Doe", email="john@example.com", mobile="9876543210")
        assert p.is_active is True
        p.deactivate()
        assert p.is_active is False
        p.activate()
        assert p.is_active is True

    def test_equality_by_email(self):
        p1 = Person(full_name="John Doe", email="john@example.com", mobile="9876543210")
        p2 = Person(full_name="Jane Doe", email="john@example.com", mobile="9988776655")
        assert p1 == p2

    def test_to_dict(self):
        p = Person(full_name="John Doe", email="john@example.com", mobile="9876543210")
        d = p.to_dict()
        assert d["full_name"] == "John Doe"
        assert d["email"] == "john@example.com"
        assert d["is_active"] is True

    def test_repr_and_str(self):
        p = Person(full_name="John Doe", email="john@example.com", mobile="9876543210")
        assert "John Doe" in repr(p)
        assert "john@example.com" in str(p)


# =========================================================================
# Patient
# =========================================================================

class TestPatient:

    def test_valid_patient(self):
        p = Patient(
            full_name="Riya Sharma",
            email="riya@example.com",
            mobile="9876543210",
            date_of_birth=date(1995, 6, 15),
            gender=Gender.FEMALE,
            blood_group=BloodGroup.O_POS,
        )
        assert p.patient_id  # UUID generated
        assert p.uhid.startswith("HMS-PAT-")
        assert p.full_name == "Riya Sharma"
        assert p.age is not None and p.age > 0

    def test_future_dob_rejected(self):
        with pytest.raises(ValueError, match="future date"):
            Patient(
                full_name="Baby Future",
                email="baby@example.com",
                mobile="9876543210",
                date_of_birth=date.today() + timedelta(days=1),
            )

    def test_address_too_long_rejected(self):
        with pytest.raises(ValueError, match="300 characters"):
            Patient(
                full_name="Long Address",
                email="long@example.com",
                mobile="9876543210",
                address="x" * 301,
            )

    def test_visit_tracking(self):
        p = Patient(full_name="Visitor", email="v@e.com", mobile="9876543210")
        assert p.visit_count == 0
        assert p.visit_type == "first_visit"
        p.record_visit()
        assert p.visit_count == 1
        p.record_visit()
        assert p.visit_count == 2
        assert p.visit_type == "returning_patient"

    def test_serialisation_roundtrip(self):
        original = Patient(
            full_name="Roundtrip",
            email="rt@example.com",
            mobile="9876543210",
            date_of_birth=date(1990, 1, 1),
            gender=Gender.MALE,
            blood_group=BloodGroup.A_POS,
            address="Somewhere",
        )
        d = original.to_dict()
        restored = Patient.from_dict(d)
        assert restored.patient_id == original.patient_id
        assert restored.uhid == original.uhid
        assert restored.full_name == original.full_name
        assert restored.email == original.email

    def test_age_none_when_no_dob(self):
        p = Patient(full_name="No DOB", email="nod@e.com", mobile="9876543210")
        assert p.age is None

    def test_repr_and_str(self):
        p = Patient(full_name="Show Me", email="show@e.com", mobile="9876543210")
        assert "Show Me" in repr(p)
        assert "show@e.com" in str(p)


# =========================================================================
# Doctor
# =========================================================================

class TestDoctor:

    def test_valid_doctor(self):
        d = Doctor(
            full_name="Dr Priya",
            email="priya@hospital.com",
            mobile="9988776655",
            specialization=Specialization.CARDIOLOGIST,
        )
        assert d.doctor_id
        assert d.uhid.startswith("HMS-DOC-")
        assert d.specialization == Specialization.CARDIOLOGIST
        assert d.max_patients_per_day == 20   # default

    def test_max_patients_too_low(self):
        with pytest.raises(ValueError, match="between 1 and 100"):
            Doctor(
                full_name="Dr Zero",
                email="zero@hosp.com",
                mobile="9988776655",
                specialization=Specialization.NEUROLOGIST,
                max_patients_per_day=0,
            )

    def test_max_patients_too_high(self):
        with pytest.raises(ValueError, match="between 1 and 100"):
            Doctor(
                full_name="Dr Max",
                email="max@hosp.com",
                mobile="9988776655",
                specialization=Specialization.NEUROLOGIST,
                max_patients_per_day=101,
            )

    def test_display_name(self):
        d = Doctor(
            full_name="Priya Nair",
            email="priya@hosp.com",
            mobile="9988776655",
            specialization=Specialization.DERMATOLOGIST,
        )
        assert "Dr. Priya Nair" in d.display_name()
        assert "Dermatologist" in d.display_name()

    def test_serialisation_roundtrip(self):
        original = Doctor(
            full_name="Dr Roundtrip",
            email="drrt@hosp.com",
            mobile="9988776655",
            specialization=Specialization.ENT_SPECIALIST,
            max_patients_per_day=15,
        )
        d = original.to_dict()
        restored = Doctor.from_dict(d)
        assert restored.doctor_id == original.doctor_id
        assert restored.uhid == original.uhid
        assert restored.specialization == Specialization.ENT_SPECIALIST


# =========================================================================
# TimeSlot
# =========================================================================

class TestTimeSlot:

    def test_valid_timeslot(self):
        ts = TimeSlot(start_time=time(9, 0), end_time=time(9, 15))
        assert ts.duration_minutes == 15

    def test_invalid_timeslot_start_after_end(self):
        with pytest.raises(ValueError, match="before end"):
            TimeSlot(start_time=time(10, 0), end_time=time(9, 0))

    def test_overlaps(self):
        ts1 = TimeSlot(start_time=time(9, 0), end_time=time(9, 30))
        ts2 = TimeSlot(start_time=time(9, 15), end_time=time(9, 45))
        ts3 = TimeSlot(start_time=time(10, 0), end_time=time(10, 30))
        assert ts1.overlaps(ts2) is True
        assert ts1.overlaps(ts3) is False


# =========================================================================
# AppointmentSlot
# =========================================================================

class TestAppointmentSlot:

    def test_is_available(self):
        s = AppointmentSlot(
            doctor_id="doc-1",
            date=date.today(),
            start_time=time(9, 0),
            end_time=time(9, 15),
        )
        assert s.is_available is True

    def test_book_and_release(self):
        s = AppointmentSlot(
            doctor_id="doc-1",
            date=date.today(),
            start_time=time(9, 0),
            end_time=time(9, 15),
        )
        s.book()
        assert s.is_booked is True
        assert s.is_available is False
        s.release()
        assert s.is_booked is False
        assert s.is_available is True

    def test_double_book_raises(self):
        s = AppointmentSlot(
            doctor_id="doc-1",
            date=date.today(),
            start_time=time(9, 0),
            end_time=time(9, 15),
        )
        s.book()
        with pytest.raises(ValueError, match="already booked"):
            s.book()

    def test_blocked_slot_not_available(self):
        s = AppointmentSlot(
            doctor_id="doc-1",
            date=date.today(),
            start_time=time(13, 0),
            end_time=time(13, 15),
            is_lunch_break=True,
            is_blocked=True,
        )
        assert s.is_available is False

    def test_serialisation_roundtrip(self):
        original = AppointmentSlot(
            doctor_id="doc-1",
            date=date.today(),
            start_time=time(10, 0),
            end_time=time(10, 15),
        )
        d = original.to_dict()
        restored = AppointmentSlot.from_dict(d)
        assert restored.slot_id == original.slot_id
        assert restored.start_time == time(10, 0)


# =========================================================================
# Slot Generation (replaces TestAvailability)
# =========================================================================

class TestSlotGeneration:

    def _future_date(self):
        d = date.today() + timedelta(days=1)
        while d.weekday() in (5, 6):
            d += timedelta(days=1)
        return d

    def test_generate_slots_contains_lunch_block(self):
        slots = generate_slots_for_doctor(
            doctor_id="doc-1",
            for_date=self._future_date(),
            work_start_time=time(9, 0),
            work_end_time=time(17, 0),
            slot_duration_minutes=15,
            max_patients_per_day=50,
        )
        lunch_slots = [s for s in slots if s.is_lunch_break]
        assert len(lunch_slots) > 0, "At least one lunch slot expected"
        for ls in lunch_slots:
            assert ls.is_blocked is True

    def test_generate_slots_count(self):
        slots = generate_slots_for_doctor(
            doctor_id="doc-1",
            for_date=self._future_date(),
            work_start_time=time(9, 0),
            work_end_time=time(10, 0),
            slot_duration_minutes=15,
            max_patients_per_day=50,
        )
        assert len(slots) == 4   # 9:00, 9:15, 9:30, 9:45

    def test_max_patients_cap(self):
        slots = generate_slots_for_doctor(
            doctor_id="doc-1",
            for_date=self._future_date(),
            work_start_time=time(9, 0),
            work_end_time=time(12, 0),
            slot_duration_minutes=15,
            max_patients_per_day=3,
        )
        bookable = [s for s in slots if s.is_available]
        assert len(bookable) == 3


# =========================================================================
# Nurse
# =========================================================================

class TestNurse:

    def test_valid_nurse(self):
        n = Nurse(
            full_name="Anjali Kumar",
            email="anjali@hospital.com",
            mobile="9876512345",
        )
        assert n.nurse_id  # UUID generated
        assert n.uhid.startswith("HMS-NRS-")
        assert n.full_name == "Anjali Kumar"

    def test_display_name(self):
        n = Nurse(
            full_name="Anjali Kumar",
            email="anjali@hospital.com",
            mobile="9876512345",
        )
        assert "Nurse Anjali Kumar" in n.display_name()

    def test_serialisation_roundtrip(self):
        original = Nurse(
            full_name="Roundtrip Nurse",
            email="rtnurse@hospital.com",
            mobile="9876512345",
        )
        d = original.to_dict()
        restored = Nurse.from_dict(d)
        assert restored.nurse_id == original.nurse_id
        assert restored.uhid == original.uhid


# =========================================================================
# Triage
# =========================================================================

class TestTriage:

    def test_valid_triage(self):
        t = Triage(
            patient_id="pat-1",
            nurse_id="nurse-1",
            doctor_id="doc-1",
            date=date.today(),
            queue_type=QueueType.NORMAL,
            blood_pressure="120/80",
            heart_rate=72,
            temperature=37.0,
        )
        assert t.triage_id
        assert t.is_emergency is False

    def test_emergency_triage(self):
        t = Triage(
            patient_id="pat-1",
            nurse_id="nurse-1",
            doctor_id="doc-1",
            date=date.today(),
            queue_type=QueueType.EMERGENCY,
        )
        assert t.is_emergency is True

    def test_invalid_heart_rate(self):
        with pytest.raises(ValueError, match="Heart rate"):
            Triage(
                patient_id="pat-1",
                nurse_id="nurse-1",
                doctor_id="doc-1",
                date=date.today(),
                heart_rate=500,
            )

    def test_invalid_temperature(self):
        with pytest.raises(ValueError, match="Temperature"):
            Triage(
                patient_id="pat-1",
                nurse_id="nurse-1",
                doctor_id="doc-1",
                date=date.today(),
                temperature=50.0,
            )

    def test_serialisation_roundtrip(self):
        original = Triage(
            patient_id="pat-1",
            nurse_id="nurse-1",
            doctor_id="doc-1",
            date=date.today(),
            queue_type=QueueType.EMERGENCY,
            blood_pressure="140/90",
            heart_rate=88,
        )
        d = original.to_dict()
        restored = Triage.from_dict(d)
        assert restored.triage_id == original.triage_id
        assert restored.queue_type == QueueType.EMERGENCY


# =========================================================================
# Appointment — status transitions
# =========================================================================

class TestAppointment:

    def _make_appointment(self, **overrides):
        defaults = {
            "patient_id": "pat-1",
            "doctor_id": "doc-1",
            "slot_id": "slot-1",
            "date": date.today() + timedelta(days=1),
            "start_time": time(9, 0),
            "end_time": time(9, 15),
        }
        defaults.update(overrides)
        return Appointment(**defaults)

    def test_initial_state_booked(self):
        apt = self._make_appointment()
        assert apt.status == AppointmentStatus.BOOKED
        assert apt.is_active is True

    def test_cancel(self):
        apt = self._make_appointment()
        apt.cancel(reason="Need to travel urgently", cancelled_by="patient")
        assert apt.status == AppointmentStatus.CANCELLED
        assert apt.cancellation_reason == "Need to travel urgently"

    def test_cancel_short_reason_rejected(self):
        apt = self._make_appointment()
        with pytest.raises(ValueError, match="10 chars"):
            apt.cancel(reason="short")

    def test_cancel_past_date_rejected(self):
        apt = self._make_appointment(date=date.today() - timedelta(days=1))
        with pytest.raises(ValueError, match="already passed"):
            apt.cancel(reason="long enough reason here")

    def test_complete(self):
        apt = self._make_appointment()
        apt.complete()
        assert apt.status == AppointmentStatus.COMPLETED

    def test_no_show(self):
        apt = self._make_appointment()
        apt.mark_no_show()
        assert apt.status == AppointmentStatus.NO_SHOW

    def test_reschedule(self):
        apt = self._make_appointment()
        apt.reschedule(
            new_slot_id="slot-2",
            new_date=date.today() + timedelta(days=2),
            new_start_time=time(10, 0),
            new_end_time=time(10, 15),
        )
        # Transient RESCHEDULED → back to BOOKED
        assert apt.status == AppointmentStatus.BOOKED
        assert apt.reschedule_count == 1
        assert apt.slot_id == "slot-2"

    def test_max_reschedule_rejected(self):
        apt = self._make_appointment()
        apt.reschedule("s2", date.today() + timedelta(days=2), time(10, 0), time(10, 15))
        apt.reschedule("s3", date.today() + timedelta(days=3), time(11, 0), time(11, 15))
        with pytest.raises(ValueError, match="reschedule limit"):
            apt.reschedule("s4", date.today() + timedelta(days=4), time(12, 0), time(12, 15))

    def test_invalid_transition(self):
        apt = self._make_appointment()
        apt.complete()
        with pytest.raises(ValueError, match="Cannot transition"):
            apt.cancel(reason="already completed rn")

    def test_emergency_flag(self):
        apt = self._make_appointment(priority=AppointmentPriority.EMERGENCY)
        assert apt.is_emergency is True

    def test_notes_sanitised(self):
        apt = self._make_appointment(notes="<script>alert('XSS')</script>")
        assert "<script>" not in apt.notes

    def test_serialisation_roundtrip(self):
        original = self._make_appointment(notes="Test notes")
        d = original.to_dict()
        restored = Appointment.from_dict(d)
        assert restored.appointment_id == original.appointment_id
        assert restored.status == AppointmentStatus.BOOKED

    def test_sorting(self):
        a1 = self._make_appointment(
            start_time=time(10, 0), end_time=time(10, 15),
            appointment_id="apt-1"
        )
        a2 = self._make_appointment(
            start_time=time(9, 0), end_time=time(9, 15),
            appointment_id="apt-2"
        )
        assert sorted([a1, a2])[0].appointment_id == a2.appointment_id


# =========================================================================
# AppointmentQueue — priority & status machine
# =========================================================================

class TestAppointmentQueue:

    def test_valid_entry(self):
        entry = AppointmentQueue(
            doctor_id="doc-1",
            date=date.today(),
            patient_id="pat-1",
            appointment_id="apt-1",
            queue_position=1,
        )
        assert entry.status == QueueStatus.WAITING
        assert entry.triage_group == TriageGroup.NORMAL

    def test_emergency_priority(self):
        entry = AppointmentQueue(
            doctor_id="doc-1",
            date=date.today(),
            patient_id="pat-1",
            appointment_id="apt-1",
            queue_position=1,
            is_emergency=True,
        )
        assert entry.triage_group == TriageGroup.EMERGENCY
        assert entry.triage_priority == 0   # lower = higher priority

    def test_status_transitions(self):
        entry = AppointmentQueue(
            doctor_id="doc-1",
            date=date.today(),
            patient_id="pat-1",
            appointment_id="apt-1",
            queue_position=1,
        )
        entry.start()
        assert entry.status == QueueStatus.IN_PROGRESS
        entry.complete()
        assert entry.status == QueueStatus.COMPLETED

    def test_invalid_transition(self):
        entry = AppointmentQueue(
            doctor_id="doc-1",
            date=date.today(),
            patient_id="pat-1",
            appointment_id="apt-1",
            queue_position=1,
        )
        with pytest.raises(ValueError, match="Invalid queue status transition"):
            entry.complete()   # can't skip to completed from waiting

    def test_invalid_position(self):
        with pytest.raises(ValueError, match="Queue position"):
            AppointmentQueue(
                doctor_id="doc-1",
                date=date.today(),
                patient_id="pat-1",
                appointment_id="apt-1",
                queue_position=0,
            )

    def test_ordering(self):
        normal = AppointmentQueue(
            doctor_id="doc-1", date=date.today(),
            patient_id="pat-1", appointment_id="apt-1",
            queue_position=1, is_emergency=False,
        )
        emergency = AppointmentQueue(
            doctor_id="doc-1", date=date.today(),
            patient_id="pat-2", appointment_id="apt-2",
            queue_position=2, is_emergency=True,
        )
        assert emergency < normal   # emergency comes first

    def test_serialisation_roundtrip(self):
        original = AppointmentQueue(
            doctor_id="doc-1", date=date.today(),
            patient_id="pat-1", appointment_id="apt-1",
            queue_position=3, is_emergency=True,
        )
        d = original.to_dict()
        restored = AppointmentQueue.from_dict(d)
        assert restored.queue_id == original.queue_id
        assert restored.is_emergency is True
