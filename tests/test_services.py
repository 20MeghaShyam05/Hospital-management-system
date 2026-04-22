# =============================================================================
# tests/test_services.py
# Integration tests for BookingService, ScheduleManager, QueueManager
# — all backed by InMemoryStore (no real DB needed)
# =============================================================================

from __future__ import annotations

import pytest
from datetime import date, time, timedelta


# =========================================================================
# BookingService — GO1 (Patient Registration)
# =========================================================================

class TestPatientRegistration:

    def test_register_new_patient(self, booking_service, sample_patient_data):
        result = booking_service.register_patient(**sample_patient_data)
        assert result["patient_id"]
        assert result["uhid"].startswith("HMS-PAT-")
        assert result["full_name"] == "Riya Sharma"
        assert result["email"] == "riya.sharma@example.com"

    def test_duplicate_email_returns_existing(self, booking_service, sample_patient_data):
        first  = booking_service.register_patient(**sample_patient_data)
        second = booking_service.register_patient(**sample_patient_data)
        # R012 — reuse existing, not create duplicate
        assert first["patient_id"] == second["patient_id"]

    def test_get_patient_by_id(self, booking_service, registered_patient):
        patient = booking_service.get_patient(registered_patient["patient_id"])
        assert patient is not None
        assert patient["email"] == registered_patient["email"]

    def test_get_patient_by_uhid(self, booking_service, registered_patient):
        patient = booking_service.get_patient(registered_patient["uhid"])
        assert patient is not None
        assert patient["patient_id"] == registered_patient["patient_id"]

    def test_list_patients(self, booking_service, registered_patient):
        patients = booking_service.list_patients()
        assert len(patients) >= 1


# =========================================================================
# BookingService — GO2 (Doctor Registration)
# =========================================================================

class TestDoctorRegistration:

    def test_register_new_doctor(self, booking_service, sample_doctor_data):
        result = booking_service.register_doctor(**sample_doctor_data)
        assert result["doctor_id"]
        assert result["uhid"].startswith("HMS-DOC-")
        assert result["specialization"] == "Cardiologist"

    def test_get_doctor_by_id(self, booking_service, registered_doctor):
        doctor = booking_service.get_doctor(registered_doctor["doctor_id"])
        assert doctor is not None
        assert doctor["specialization"] == "Cardiologist"

    def test_get_doctor_by_uhid(self, booking_service, registered_doctor):
        doctor = booking_service.get_doctor(registered_doctor["uhid"])
        assert doctor is not None
        assert doctor["doctor_id"] == registered_doctor["doctor_id"]

    def test_list_doctors(self, booking_service, registered_doctor):
        doctors = booking_service.list_doctors()
        assert len(doctors) >= 1

# =========================================================================
# Auto-slot generation + Per-doctor work times + Specialization consultation times
# =========================================================================

class TestAutoSlotGeneration:

    def test_slots_auto_generated_on_registration(self, booking_service, future_weekday):
        """Registering a doctor should auto-generate slots for upcoming weekdays."""
        result = booking_service.register_doctor(
            full_name="Dr Auto Slots",
            email="auto@hospital.com",
            mobile="9988776600",
            specialization="General Physician",
        )
        # Slots should already exist for the next weekday
        slots = booking_service.get_available_slots(result["doctor_id"], future_weekday)
        assert len(slots) > 0, "Expected auto-generated slots after registration"

    def test_specialization_consultation_time_applied(self, booking_service, future_weekday):
        """General Physician should have 10-min slots, Cardiologist 20-min."""
        gp = booking_service.register_doctor(
            full_name="Dr GP Ten",
            email="gp10@hospital.com",
            mobile="9988776601",
            specialization="General Physician",
        )
        # GP consultation is 10 minutes
        assert gp.get("consultation_duration_minutes") == 10

        cardio = booking_service.register_doctor(
            full_name="Dr Cardio Twenty",
            email="cardio20@hospital.com",
            mobile="9988776602",
            specialization="Cardiologist",
        )
        # Cardiologist consultation is 20 minutes
        assert cardio.get("consultation_duration_minutes") == 20

    def test_specialization_different_slot_counts(self, booking_service, future_weekday):
        """Different specializations generate different numbers of slots
        because their consultation durations differ."""
        gp = booking_service.register_doctor(
            full_name="Dr GP Slots",
            email="gp_slots@hospital.com",
            mobile="9988776603",
            specialization="General Physician",
        )
        psych = booking_service.register_doctor(
            full_name="Dr Psych Slots",
            email="psych_slots@hospital.com",
            mobile="9988776604",
            specialization="Psychiatrist",
        )
        gp_slots = booking_service.get_available_slots(gp["doctor_id"], future_weekday)
        psych_slots = booking_service.get_available_slots(psych["doctor_id"], future_weekday)
        # GP (10 min) should have more slots than Psychiatrist (30 min)
        assert len(gp_slots) > len(psych_slots)

    def test_per_doctor_work_hours_stored(self, booking_service):
        """Doctor's work hours should reflect specialization defaults."""
        result = booking_service.register_doctor(
            full_name="Dr Ortho Hours",
            email="ortho@hospital.com",
            mobile="9988776605",
            specialization="Orthopedist",
        )
        # Orthopedist defaults: 08:00 - 15:00
        assert result.get("work_start_time") == "08:00:00"
        assert result.get("work_end_time") == "15:00:00"

    def test_custom_work_hours_override(self, booking_service, future_weekday):
        """Doctor can override specialization default work hours."""
        from datetime import time as t
        result = booking_service.register_doctor(
            full_name="Dr Custom Hours",
            email="custom@hospital.com",
            mobile="9988776606",
            specialization="General Physician",
            work_start_time=t(10, 0),
            work_end_time=t(14, 0),
        )
        assert result.get("work_start_time") == "10:00:00"
        assert result.get("work_end_time") == "14:00:00"

    def test_custom_consultation_duration_override(self, booking_service):
        """Doctor can override specialization default consultation duration."""
        result = booking_service.register_doctor(
            full_name="Dr Custom Duration",
            email="custom_dur@hospital.com",
            mobile="9988776607",
            specialization="General Physician",
            consultation_duration_minutes=20,   # override default 10
        )
        assert result.get("consultation_duration_minutes") == 20

    def test_psychiatrist_has_30min_slots(self, booking_service, future_weekday):
        """Psychiatrist consultation = 30 minutes per NSL spec."""
        psych = booking_service.register_doctor(
            full_name="Dr Long Session",
            email="long@hospital.com",
            mobile="9988776608",
            specialization="Psychiatrist",
        )
        assert psych.get("consultation_duration_minutes") == 30
        # Verify the actual slot duration
        slots = booking_service.get_available_slots(psych["doctor_id"], future_weekday)
        if len(slots) >= 2:
            # Each slot should be 30 min apart
            s1_start = slots[0]["start_time"]
            s2_start = slots[1]["start_time"]
            # Parse times and check difference
            from datetime import datetime as dt
            t1 = dt.strptime(s1_start, "%H:%M:%S") if isinstance(s1_start, str) else dt.combine(future_weekday, s1_start)
            t2 = dt.strptime(s2_start, "%H:%M:%S") if isinstance(s2_start, str) else dt.combine(future_weekday, s2_start)
            diff_minutes = abs((t2 - t1).total_seconds()) / 60
            assert diff_minutes == 30, f"Expected 30-minute slots, got {diff_minutes}"

    def test_no_duplicate_slots_on_re_registration(self, booking_service, future_weekday):
        """Re-registering a doctor (email upsert) should not duplicate slots."""
        result1 = booking_service.register_doctor(
            full_name="Dr First Reg",
            email="noreg@hospital.com",
            mobile="9988776609",
            specialization="Dermatologist",
        )
        slots1 = booking_service.get_available_slots(result1["doctor_id"], future_weekday)

        # Re-register with same email (E7 upsert) — slots should not duplicate
        result2 = booking_service.register_doctor(
            full_name="Dr First Reg Updated",
            email="noreg@hospital.com",
            mobile="9988776609",
            specialization="Dermatologist",
        )
        slots2 = booking_service.get_available_slots(result1["doctor_id"], future_weekday)
        assert len(slots2) == len(slots1), "Re-registration should not duplicate slots"

    def test_re_registration_uses_persisted_doctor_id_for_slots(self, booking_service, future_weekday):
        first = booking_service.register_doctor(
            full_name="Dr Stable ID",
            email="stable@hospital.com",
            mobile="9988776610",
            specialization="Cardiologist",
        )
        second = booking_service.register_doctor(
            full_name="Dr Stable ID Updated",
            email="stable@hospital.com",
            mobile="9988776611",
            specialization="Cardiologist",
        )
        assert first["doctor_id"] == second["doctor_id"]
        slots = booking_service.get_available_slots(first["doctor_id"], future_weekday)
        assert len(slots) > 0


# =========================================================================
# BookingService — GO3 (Auto-Generated Slots)
# =========================================================================

class TestSlotsAutoGenerated:

    def test_get_available_slots(self, booking_service, doctor_with_slots, future_weekday):
        slots = booking_service.get_available_slots(
            doctor_with_slots["doctor_id"], future_weekday
        )
        assert len(slots) > 0
        # No lunch slots should appear
        for s in slots:
            assert s["is_lunch_break"] is False
            assert s["is_booked"] is False
            assert s["is_blocked"] is False

    def test_on_demand_slot_generation(self, booking_service, registered_doctor):
        """Requesting slots for a weekday that wasn't pre-generated should auto-create them."""
        far_d = date.today() + timedelta(days=20)
        while far_d.weekday() in (5, 6):
            far_d += timedelta(days=1)
        slots = booking_service.get_available_slots(registered_doctor["doctor_id"], far_d)
        assert len(slots) > 0, "On-demand slot generation should create slots"


# =========================================================================
# Nurse Registration
# =========================================================================

class TestNurseRegistration:

    def test_register_nurse(self, booking_service, sample_nurse_data):
        result = booking_service.register_nurse(**sample_nurse_data)
        assert result["nurse_id"]
        assert result["full_name"] == "Anjali Kumar"

    def test_get_nurse_by_id(self, booking_service, registered_nurse):
        nurse = booking_service.get_nurse(registered_nurse["nurse_id"])
        assert nurse is not None
        assert nurse["email"] == registered_nurse["email"]

    def test_list_nurses(self, booking_service, registered_nurse):
        nurses = booking_service.list_nurses()
        assert len(nurses) >= 1


# =========================================================================
# Triage Operations
# =========================================================================

class TestTriageOperations:

    def test_create_triage_entry(
        self, booking_service, registered_patient, registered_nurse,
        registered_doctor, future_weekday
    ):
        result = booking_service.create_triage_entry(
            patient_id=registered_patient["patient_id"],
            nurse_id=registered_nurse["nurse_id"],
            doctor_id=registered_doctor["doctor_id"],
            triage_date=future_weekday,
            queue_type="normal",
            blood_pressure="120/80",
            heart_rate=72,
            temperature=37.0,
        )
        assert result["triage_id"]
        assert result["queue_type"] == "normal"

    def test_emergency_triage(
        self, booking_service, registered_patient, registered_nurse,
        registered_doctor, future_weekday
    ):
        result = booking_service.create_triage_entry(
            patient_id=registered_patient["patient_id"],
            nurse_id=registered_nurse["nurse_id"],
            doctor_id=registered_doctor["doctor_id"],
            triage_date=future_weekday,
            queue_type="emergency",
        )
        assert result["queue_type"] == "emergency"

    def test_triage_with_invalid_patient(
        self, booking_service, registered_nurse, registered_doctor, future_weekday
    ):
        with pytest.raises(ValueError, match="not found"):
            booking_service.create_triage_entry(
                patient_id="nonexistent-patient",
                nurse_id=registered_nurse["nurse_id"],
                doctor_id=registered_doctor["doctor_id"],
                triage_date=future_weekday,
            )


# =========================================================================
# BookingService — GO4 (Book Appointment)
# =========================================================================

class TestBookAppointment:

    def test_book_appointment_success(
        self, booking_service, registered_patient, doctor_with_slots,
        available_slot, future_weekday
    ):
        result = booking_service.book_appointment(
            patient_id=registered_patient["uhid"],
            doctor_id=doctor_with_slots["uhid"],
            slot_id=available_slot["slot_id"],
            appointment_date=future_weekday,
            notes="Routine checkup",
            priority="normal",
        )
        assert result["appointment_id"]
        assert result["status"] == "booked"
        assert result["queue_position"] >= 1

    def test_past_date_rejected(
        self, booking_service, registered_patient, doctor_with_slots, available_slot
    ):
        with pytest.raises(ValueError, match="past date"):
            booking_service.book_appointment(
                patient_id=registered_patient["patient_id"],
                doctor_id=doctor_with_slots["doctor_id"],
                slot_id=available_slot["slot_id"],
                appointment_date=date.today() - timedelta(days=1),
            )

    def test_weekend_rejected(
        self, booking_service, registered_patient, doctor_with_slots, available_slot
    ):
        # Find the next Saturday
        d = date.today()
        while d.weekday() != 5:
            d += timedelta(days=1)
        with pytest.raises(ValueError, match="weekend"):
            booking_service.book_appointment(
                patient_id=registered_patient["patient_id"],
                doctor_id=doctor_with_slots["doctor_id"],
                slot_id=available_slot["slot_id"],
                appointment_date=d,
            )

    def test_nonexistent_patient_rejected(
        self, booking_service, doctor_with_slots, available_slot, future_weekday
    ):
        with pytest.raises(ValueError, match="not found"):
            booking_service.book_appointment(
                patient_id="nonexistent-patient-id",
                doctor_id=doctor_with_slots["doctor_id"],
                slot_id=available_slot["slot_id"],
                appointment_date=future_weekday,
            )

    def test_nonexistent_doctor_rejected(
        self, booking_service, registered_patient, available_slot, future_weekday
    ):
        with pytest.raises(ValueError, match="not found"):
            booking_service.book_appointment(
                patient_id=registered_patient["patient_id"],
                doctor_id="nonexistent-doctor-id",
                slot_id=available_slot["slot_id"],
                appointment_date=future_weekday,
            )

    def test_slot_marked_booked_after_booking(
        self, booking_service, in_memory_store, registered_patient,
        doctor_with_slots, available_slot, future_weekday
    ):
        booking_service.book_appointment(
            patient_id=registered_patient["patient_id"],
            doctor_id=doctor_with_slots["doctor_id"],
            slot_id=available_slot["slot_id"],
            appointment_date=future_weekday,
        )
        slot = in_memory_store.get_slot(available_slot["slot_id"])
        assert slot["is_booked"] is True

    def test_slot_from_different_doctor_rejected(self, booking_service, registered_patient, future_weekday):
        doctor_one = booking_service.register_doctor(
            full_name="Dr One",
            email="doc.one@hospital.com",
            mobile="9988776612",
            specialization="General Physician",
        )
        doctor_two = booking_service.register_doctor(
            full_name="Dr Two",
            email="doc.two@hospital.com",
            mobile="9988776613",
            specialization="General Physician",
        )
        slot = booking_service.get_available_slots(doctor_one["doctor_id"], future_weekday)[0]
        with pytest.raises(ValueError, match="requested doctor"):
            booking_service.book_appointment(
                patient_id=registered_patient["patient_id"],
                doctor_id=doctor_two["doctor_id"],
                slot_id=slot["slot_id"],
                appointment_date=future_weekday,
            )

    def test_slot_from_different_date_rejected(
        self, booking_service, registered_patient, doctor_with_slots, future_weekday
    ):
        next_day = future_weekday + timedelta(days=1)
        while next_day.weekday() in (5, 6):
            next_day += timedelta(days=1)
        slot = booking_service.get_available_slots(doctor_with_slots["doctor_id"], future_weekday)[0]
        with pytest.raises(ValueError, match="appointment date"):
            booking_service.book_appointment(
                patient_id=registered_patient["patient_id"],
                doctor_id=doctor_with_slots["doctor_id"],
                slot_id=slot["slot_id"],
                appointment_date=next_day,
            )

    def test_emergency_priority_is_persisted(
        self, booking_service, registered_patient, doctor_with_slots,
        available_slot, future_weekday
    ):
        result = booking_service.book_appointment(
            patient_id=registered_patient["patient_id"],
            doctor_id=doctor_with_slots["doctor_id"],
            slot_id=available_slot["slot_id"],
            appointment_date=future_weekday,
            priority="emergency",
        )
        assert result["priority"] == "emergency"

    def test_double_booking_same_slot_rejected(
        self, booking_service, registered_patient, doctor_with_slots,
        available_slot, future_weekday
    ):
        """Appointment conflict test — no double booking allowed."""
        second_patient = booking_service.register_patient(
            full_name="Second Patient",
            email="second.patient@example.com",
            mobile="9111222333",
            gender="Male",
            blood_group="O+",
        )
        booking_service.book_appointment(
            patient_id=registered_patient["patient_id"],
            doctor_id=doctor_with_slots["doctor_id"],
            slot_id=available_slot["slot_id"],
            appointment_date=future_weekday,
        )
        with pytest.raises(ValueError, match="not available"):
            booking_service.book_appointment(
                patient_id=second_patient["patient_id"],
                doctor_id=doctor_with_slots["doctor_id"],
                slot_id=available_slot["slot_id"],
                appointment_date=future_weekday,
            )


# =========================================================================
# BookingService — GO5 (Cancel Appointment)
# =========================================================================

class TestCancelAppointment:

    def _book(self, booking_service, patient, doctor, slot, for_date):
        return booking_service.book_appointment(
            patient_id=patient["patient_id"],
            doctor_id=doctor["doctor_id"],
            slot_id=slot["slot_id"],
            appointment_date=for_date,
        )

    def test_cancel_success(
        self, booking_service, registered_patient, doctor_with_slots,
        available_slot, future_weekday
    ):
        booked = self._book(
            booking_service, registered_patient, doctor_with_slots,
            available_slot, future_weekday
        )
        result = booking_service.cancel_appointment(
            appointment_id=booked["appointment_id"],
            reason="Need to travel — family emergency",
            cancelled_by="patient",
        )
        assert result["status"] == "cancelled"

    def test_cancel_releases_slot(
        self, booking_service, in_memory_store, registered_patient,
        doctor_with_slots, available_slot, future_weekday
    ):
        booked = self._book(
            booking_service, registered_patient, doctor_with_slots,
            available_slot, future_weekday
        )
        booking_service.cancel_appointment(
            appointment_id=booked["appointment_id"],
            reason="Releasing the slot for others",
        )
        slot = in_memory_store.get_slot(available_slot["slot_id"])
        assert slot["is_booked"] is False

    def test_cancel_short_reason_rejected(
        self, booking_service, registered_patient, doctor_with_slots,
        available_slot, future_weekday
    ):
        booked = self._book(
            booking_service, registered_patient, doctor_with_slots,
            available_slot, future_weekday
        )
        with pytest.raises(ValueError, match="10 chars"):
            booking_service.cancel_appointment(
                appointment_id=booked["appointment_id"],
                reason="short",
            )

    def test_cancel_nonexistent_rejected(self, booking_service):
        with pytest.raises(ValueError, match="not found"):
            booking_service.cancel_appointment(
                appointment_id="nonexistent-apt",
                reason="This appointment does not exist at all",
            )


# =========================================================================
# BookingService — GO6 (Reschedule Appointment)
# =========================================================================

class TestRescheduleAppointment:

    def _book(self, booking_service, patient, doctor, slot, for_date):
        return booking_service.book_appointment(
            patient_id=patient["patient_id"],
            doctor_id=doctor["doctor_id"],
            slot_id=slot["slot_id"],
            appointment_date=for_date,
        )

    def test_reschedule_success(
        self, booking_service, registered_patient, doctor_with_slots,
        future_weekday
    ):
        slots = booking_service.get_available_slots(
            doctor_with_slots["doctor_id"], future_weekday
        )
        booked = self._book(
            booking_service, registered_patient, doctor_with_slots,
            slots[0], future_weekday
        )
        result = booking_service.reschedule_appointment(
            appointment_id=booked["appointment_id"],
            new_slot_id=slots[1]["slot_id"],
            new_date=future_weekday,
        )
        assert result["slot_id"] == slots[1]["slot_id"]
        assert result["reschedule_count"] == 1

    def test_reschedule_nonexistent_rejected(self, booking_service, future_weekday):
        with pytest.raises(ValueError, match="not found"):
            booking_service.reschedule_appointment(
                appointment_id="nonexistent",
                new_slot_id="any-slot",
                new_date=future_weekday,
            )

    def test_reschedule_rejects_slot_date_mismatch(
        self, booking_service, registered_patient, doctor_with_slots, future_weekday
    ):
        slots = booking_service.get_available_slots(doctor_with_slots["doctor_id"], future_weekday)
        booked = self._book(
            booking_service, registered_patient, doctor_with_slots,
            slots[0], future_weekday
        )
        next_day = future_weekday + timedelta(days=1)
        while next_day.weekday() in (5, 6):
            next_day += timedelta(days=1)
        with pytest.raises(ValueError, match="appointment date"):
            booking_service.reschedule_appointment(
                appointment_id=booked["appointment_id"],
                new_slot_id=slots[1]["slot_id"],
                new_date=next_day,
            )


# =========================================================================
# ScheduleManager — binary search, caching, helpers
# =========================================================================

class TestScheduleManager:

    def test_find_slot_by_time(
        self, schedule_manager, booking_service, doctor_with_slots, future_weekday
    ):
        slot = schedule_manager.find_slot_by_time(
            doctor_with_slots["doctor_id"], future_weekday, time(9, 0)
        )
        assert slot is not None
        assert slot["start_time"] == "09:00:00"

    def test_find_slot_by_time_not_found(
        self, schedule_manager, doctor_with_slots, future_weekday
    ):
        slot = schedule_manager.find_slot_by_time(
            doctor_with_slots["doctor_id"], future_weekday, time(23, 0)
        )
        assert slot is None

    def test_is_weekend(self, schedule_manager):
        # Find a Saturday
        d = date.today()
        while d.weekday() != 5:
            d += timedelta(days=1)
        assert schedule_manager.is_weekend(d) is True

    def test_is_not_weekend(self, schedule_manager):
        # Find a Monday
        d = date.today()
        while d.weekday() != 0:
            d += timedelta(days=1)
        assert schedule_manager.is_weekend(d) is False

    def test_is_lunch_time(self, schedule_manager):
        assert schedule_manager.is_lunch_time(time(13, 0), time(13, 15)) is True
        assert schedule_manager.is_lunch_time(time(9, 0), time(9, 15)) is False

    def test_cache_invalidation(
        self, schedule_manager, doctor_with_slots, future_weekday
    ):
        doc_id = doctor_with_slots["doctor_id"]
        # First call populates cache
        slots1 = schedule_manager.get_available_slots(doc_id, future_weekday)
        # Invalidate
        schedule_manager.invalidate_cache(doc_id, future_weekday.isoformat())
        # Second call should still return same data (from DB, not cache)
        slots2 = schedule_manager.get_available_slots(doc_id, future_weekday)
        assert len(slots1) == len(slots2)

    def test_slot_time_labels(self, schedule_manager, doctor_with_slots, future_weekday):
        slots = schedule_manager.get_available_slots(
            doctor_with_slots["doctor_id"], future_weekday
        )
        labels = schedule_manager.slot_time_labels(slots)
        assert len(labels) == len(slots)
        assert "AM" in labels[0] or "PM" in labels[0]

    def test_rank_doctors_by_slot_count(
        self, schedule_manager, booking_service, doctor_with_slots, future_weekday
    ):
        doctors = booking_service.list_doctors()
        ranked = schedule_manager.rank_doctors_by_availability(future_weekday, doctors)
        assert len(ranked) >= 1
        assert "available_slots" in ranked[0]


# =========================================================================
# QueueManager — enqueue, dequeue, priority, complete, no-show
# =========================================================================

class TestQueueManager:

    def test_enqueue_normal(self, queue_manager, future_weekday):
        entry = queue_manager.enqueue(
            doctor_id="doc-1",
            for_date=future_weekday,
            patient_id="pat-1",
            appointment_id="apt-1",
        )
        assert entry.queue_position == 1
        assert entry.is_emergency is False

    def test_enqueue_emergency(self, queue_manager, future_weekday):
        entry = queue_manager.enqueue(
            doctor_id="doc-1",
            for_date=future_weekday,
            patient_id="pat-1",
            appointment_id="apt-1",
            is_emergency=True,
        )
        assert entry.is_emergency is True

    def test_dequeue_emergency_first(self, queue_manager, future_weekday):
        # Enqueue normal first, then emergency
        queue_manager.enqueue("doc-1", future_weekday, "pat-normal", "apt-n")
        queue_manager.enqueue("doc-1", future_weekday, "pat-emerg", "apt-e", is_emergency=True)

        # Dequeue should return emergency first (R130)
        first = queue_manager.dequeue("doc-1", future_weekday)
        assert first is not None
        assert first.patient_id == "pat-emerg"

    def test_complete(self, queue_manager, future_weekday):
        queue_manager.enqueue("doc-1", future_weekday, "pat-1", "apt-1")
        entry = queue_manager.dequeue("doc-1", future_weekday)
        completed = queue_manager.complete("doc-1", "apt-1")
        assert completed.status.value == "completed"

    def test_no_show(self, queue_manager, future_weekday):
        queue_manager.enqueue("doc-1", future_weekday, "pat-1", "apt-1")
        queue_manager.dequeue("doc-1", future_weekday)
        result = queue_manager.mark_no_show("doc-1", "apt-1")
        assert result.status.value == "no-show"

    def test_queue_summary(self, queue_manager, future_weekday):
        queue_manager.enqueue("doc-1", future_weekday, "pat-1", "apt-1")
        queue_manager.enqueue("doc-1", future_weekday, "pat-2", "apt-2", is_emergency=True)
        summary = queue_manager.get_queue_summary("doc-1", future_weekday)
        assert summary["total"] == 2
        assert summary["emergency"] == 1

    def test_cancel_entry(self, queue_manager, future_weekday):
        queue_manager.enqueue("doc-1", future_weekday, "pat-1", "apt-1")
        found = queue_manager.cancel_entry("doc-1", future_weekday, "apt-1")
        assert found is True
        summary = queue_manager.get_queue_summary("doc-1", future_weekday)
        assert summary["total"] == 0

    def test_estimate_wait(self, queue_manager, future_weekday):
        queue_manager.enqueue("doc-1", future_weekday, "pat-1", "apt-1")
        queue_manager.enqueue("doc-1", future_weekday, "pat-2", "apt-2")
        wait = queue_manager.estimate_wait_minutes(
            "doc-1", future_weekday, "apt-2", slot_duration_minutes=15
        )
        assert wait == 15   # one patient ahead × 15 min

    def test_stream_queue_generator(self, queue_manager, future_weekday):
        queue_manager.enqueue("doc-1", future_weekday, "pat-1", "apt-1")
        gen = queue_manager.stream_queue("doc-1", future_weekday)
        entries = list(gen)
        assert len(entries) == 1

    def test_triage_groups(self, queue_manager, future_weekday):
        for i in range(7):
            queue_manager.enqueue("doc-1", future_weekday, f"pat-{i}", f"apt-{i}")
        groups = queue_manager.triage_groups("doc-1", future_weekday, capacity_per_group=3)
        assert len(groups) == 3   # 3 + 3 + 1
        assert groups[0]["size"] == 3
        assert groups[2]["size"] == 1
