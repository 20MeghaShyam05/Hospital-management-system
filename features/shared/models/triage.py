# =============================================================================
# models/triage.py
# Triage entity — records patient vitals and queue assignment
# =============================================================================
# Nurses use this to record patient vitals when they arrive and decide
# which queue (normal or emergency) the patient should be placed in.
# =============================================================================

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import uuid4


class QueueType(str, Enum):
    """Queue assignment made by the nurse during triage."""
    NORMAL    = "normal"       # Non-emergency — FIFO scheduling
    EMERGENCY = "emergency"    # Priority queue — treated first


def _next_triage_id() -> str:
    return str(uuid4())


class Triage:
    """Records patient vitals and queue assignment by a nurse.

    When a patient arrives for their appointment, a nurse records their
    vitals and determines whether they should be placed in the normal
    queue (FIFO) or the priority/emergency queue.

    Attributes
    ----------
    triage_id         : str — unique ID
    patient_id        : str — FK to patients
    nurse_id          : str — FK to nurses (who performed triage)
    doctor_id         : str — FK to doctors (the patient's doctor)
    appointment_id    : str — FK to appointments (nullable)
    date              : date — triage date
    blood_pressure    : str — e.g., "120/80"
    heart_rate        : int — beats per minute
    temperature       : float — in Celsius
    weight            : float — in kg
    oxygen_saturation : float — SpO2 percentage
    symptoms          : str — patient-reported symptoms
    queue_type        : QueueType — normal or emergency
    notes             : str — nurse notes
    created_at        : datetime — when the triage was recorded
    """

    def __init__(
        self,
        patient_id: str,
        nurse_id: str,
        doctor_id: str,
        date: date,
        queue_type: QueueType = QueueType.NORMAL,
        appointment_id: Optional[str] = None,
        blood_pressure: Optional[str] = None,
        heart_rate: Optional[int] = None,
        temperature: Optional[float] = None,
        weight: Optional[float] = None,
        oxygen_saturation: Optional[float] = None,
        symptoms: Optional[str] = None,
        notes: Optional[str] = None,
        triage_id: Optional[str] = None,
    ) -> None:
        if not patient_id or not str(patient_id).strip():
            raise ValueError("patient_id must be a non-empty string.")
        if not nurse_id or not str(nurse_id).strip():
            raise ValueError("nurse_id must be a non-empty string.")
        if not doctor_id or not str(doctor_id).strip():
            raise ValueError("doctor_id must be a non-empty string.")

        # Validate vitals ranges if provided
        if heart_rate is not None and (heart_rate < 20 or heart_rate > 300):
            raise ValueError("Heart rate must be between 20 and 300 bpm.")
        if temperature is not None and (temperature < 30.0 or temperature > 45.0):
            raise ValueError("Temperature must be between 30.0 and 45.0 °C.")
        if weight is not None and (weight < 0.5 or weight > 500.0):
            raise ValueError("Weight must be between 0.5 and 500.0 kg.")
        if oxygen_saturation is not None and (oxygen_saturation < 0 or oxygen_saturation > 100):
            raise ValueError("Oxygen saturation must be between 0 and 100%.")

        self.patient_id:        str           = patient_id
        self.nurse_id:          str           = nurse_id
        self.doctor_id:         str           = doctor_id
        self.appointment_id:    Optional[str] = appointment_id
        self.date:              date          = date
        self.blood_pressure:    Optional[str] = blood_pressure
        self.heart_rate:        Optional[int] = heart_rate
        self.temperature:       Optional[float] = temperature
        self.weight:            Optional[float] = weight
        self.oxygen_saturation: Optional[float] = oxygen_saturation
        self.symptoms:          Optional[str] = symptoms
        self.queue_type:        QueueType     = queue_type
        self.notes:             Optional[str] = notes
        self.created_at:        datetime      = datetime.now()

        self.triage_id: str = triage_id or _next_triage_id()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def is_emergency(self) -> bool:
        return self.queue_type == QueueType.EMERGENCY

    # ------------------------------------------------------------------
    # Magic methods
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Triage("
            f"triage_id={self.triage_id!r}, "
            f"patient_id={self.patient_id!r}, "
            f"nurse_id={self.nurse_id!r}, "
            f"queue_type={self.queue_type.value!r}"
            f")"
        )

    def __str__(self) -> str:
        flag = " 🚨 EMERGENCY" if self.is_emergency else ""
        return (
            f"[{self.triage_id}] Patient {self.patient_id} | "
            f"Nurse {self.nurse_id} | "
            f"Queue: {self.queue_type.value.upper()}{flag}"
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "triage_id":         self.triage_id,
            "patient_id":       self.patient_id,
            "nurse_id":         self.nurse_id,
            "doctor_id":        self.doctor_id,
            "appointment_id":   self.appointment_id,
            "date":             self.date.isoformat(),
            "blood_pressure":   self.blood_pressure,
            "heart_rate":       self.heart_rate,
            "temperature":      self.temperature,
            "weight":           self.weight,
            "oxygen_saturation": self.oxygen_saturation,
            "symptoms":         self.symptoms,
            "queue_type":       self.queue_type.value,
            "notes":            self.notes,
            "created_at":       self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Triage":
        t = cls(
            patient_id=data["patient_id"],
            nurse_id=data["nurse_id"],
            doctor_id=data["doctor_id"],
            date=date.fromisoformat(data["date"]) if isinstance(data["date"], str) else data["date"],
            queue_type=QueueType(data.get("queue_type", "normal")),
            appointment_id=data.get("appointment_id"),
            blood_pressure=data.get("blood_pressure"),
            heart_rate=data.get("heart_rate"),
            temperature=data.get("temperature"),
            weight=data.get("weight"),
            oxygen_saturation=data.get("oxygen_saturation"),
            symptoms=data.get("symptoms"),
            notes=data.get("notes"),
            triage_id=data.get("triage_id"),
        )
        if data.get("created_at"):
            t.created_at = (
                datetime.fromisoformat(data["created_at"])
                if isinstance(data["created_at"], str)
                else data["created_at"]
            )
        return t
