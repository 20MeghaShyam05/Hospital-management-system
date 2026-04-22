# =============================================================================
# models/__init__.py
# Doctor–Patient Appointment Management System (DPAS)
# =============================================================================
# This file turns the `models` directory into a Python package and exports
# every public class, enum, and dataclass the rest of the app needs.
# Import from here so the rest of the codebase never has to know which
# sub-module a symbol lives in:
#
#   from models import Patient, Doctor, Appointment, AppointmentStatus ...
# =============================================================================

from features.shared.models.person import Person
from features.shared.models.patient import Patient
from features.shared.models.doctor import Doctor, Specialization
from features.shared.models.nurse import Nurse
from features.shared.models.appointment import (
    Appointment,
    AppointmentStatus,
    AppointmentPriority,
)
from features.shared.models.slot import TimeSlot, AppointmentSlot, generate_slots_for_doctor
from features.shared.models.queue import AppointmentQueue, TriageGroup
from features.shared.models.triage import Triage, QueueType

__all__ = [
    # Base
    "Person",
    # Patient side
    "Patient",
    # Doctor side
    "Doctor",
    "Specialization",
    # Nurse
    "Nurse",
    # Appointment
    "Appointment",
    "AppointmentStatus",
    "AppointmentPriority",
    # Slots
    "TimeSlot",
    "AppointmentSlot",
    "generate_slots_for_doctor",
    # Queue
    "AppointmentQueue",
    "TriageGroup",
    # Triage
    "Triage",
    "QueueType",
]
