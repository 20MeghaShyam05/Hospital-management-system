from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import hmac
import json
import time
from typing import Optional

from config import settings
from features.shared.utils.rbac import RBACError, Role


class AuthService:
    """Small auth service for role-based login with signed stateless tokens."""

    def __init__(self, db) -> None:
        self._db = db
        self._admin_user = {
            "user_id": "admin",
            "username": settings.ADMIN_USERNAME,
            "role": Role.ADMIN.value,
            "display_name": "System Admin",
        }
        self._front_desk_user = {
            "user_id": "frontdesk",
            "username": settings.FRONT_DESK_USERNAME,
            "role": Role.FRONT_DESK.value,
            "display_name": "Front Desk",
        }

    @staticmethod
    def hash_password(password: str) -> str:
        salt = hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:32]
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
        return f"{salt}${digest}"

    @classmethod
    def verify_password(cls, password: str, password_hash: Optional[str]) -> bool:
        if not password_hash:
            return False
        try:
            salt, digest = password_hash.split("$", 1)
        except ValueError:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
        return hmac.compare_digest(candidate, digest)

    @staticmethod
    def _b64encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    @staticmethod
    def _b64decode(data: str) -> bytes:
        padding = "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(data + padding)

    def _sign(self, payload_b64: str) -> str:
        signature = hmac.new(
            settings.JWT_SECRET.encode(),
            payload_b64.encode(),
            hashlib.sha256,
        ).digest()
        return self._b64encode(signature)

    def issue_token(self, user: dict) -> str:
        payload = {
            **user,
            "exp": int(time.time()) + settings.JWT_EXPIRE_MIN * 60,
        }
        payload_b64 = self._b64encode(json.dumps(payload, separators=(",", ":")).encode())
        return f"{payload_b64}.{self._sign(payload_b64)}"

    def decode_token(self, token: str) -> dict:
        try:
            payload_b64, signature = token.split(".", 1)
        except ValueError as exc:
            raise RBACError("Invalid authentication token format.") from exc
        if not hmac.compare_digest(signature, self._sign(payload_b64)):
            raise RBACError("Invalid authentication token signature.")
        payload = json.loads(self._b64decode(payload_b64).decode())
        if int(payload.get("exp", 0)) < int(time.time()):
            raise RBACError("Authentication token has expired.")
        return payload

    def _build_patient_user(self, patient: dict) -> dict:
        return {
            "user_id": patient["patient_id"],
            "role": Role.PATIENT.value,
            "display_name": patient["full_name"],
            "linked_patient_id": patient["patient_id"],
            "linked_patient_uhid": patient.get("uhid"),
        }

    def _build_doctor_user(self, doctor: dict) -> dict:
        return {
            "user_id": doctor["doctor_id"],
            "role": Role.DOCTOR.value,
            "display_name": doctor["full_name"],
            "linked_doctor_id": doctor["doctor_id"],
            "linked_doctor_uhid": doctor.get("uhid"),
        }

    def _build_nurse_user(self, nurse: dict) -> dict:
        return {
            "user_id": nurse["nurse_id"],
            "role": Role.NURSE.value,
            "display_name": nurse["full_name"],
            "linked_nurse_id": nurse["nurse_id"],
            "linked_nurse_uhid": nurse.get("uhid"),
        }

    def login(self, identifier: str, password: str, role: str) -> dict:
        requested_role = Role(role)

        if requested_role == Role.ADMIN:
            if identifier.strip().lower() != self._admin_user["username"].lower():
                raise RBACError("Invalid username, password, or role.")
            if password != settings.ADMIN_PASSWORD:
                raise RBACError("Invalid username, password, or role.")
            user = dict(self._admin_user)
            return {"access_token": self.issue_token(user), "user": user}

        if requested_role == Role.FRONT_DESK:
            if identifier.strip().lower() != self._front_desk_user["username"].lower():
                raise RBACError("Invalid username, password, or role.")
            if password != settings.FRONT_DESK_PASSWORD:
                raise RBACError("Invalid username, password, or role.")
            user = dict(self._front_desk_user)
            return {"access_token": self.issue_token(user), "user": user}

        if requested_role == Role.PATIENT:
            patient = (
                self._db.get_patient_by_id(identifier)
                or self._db.get_patient_by_uhid(identifier)
                or self._db.get_patient_by_email(identifier.lower())
            )
            if not patient:
                raise RBACError("Invalid patient credentials.")
            password_hash = patient.get("password_hash")
            if password_hash:
                if not self.verify_password(password, password_hash):
                    raise RBACError("Invalid patient credentials.")
            elif patient.get("mobile") != password:
                raise RBACError("Invalid patient credentials.")
            user = self._build_patient_user(patient)
            return {"access_token": self.issue_token(user), "user": user}

        if requested_role == Role.DOCTOR:
            doctor = (
                self._db.get_doctor_by_id(identifier)
                or self._db.get_doctor_by_uhid(identifier)
                or self._db.get_doctor_by_email(identifier.lower())
            )
            if not doctor:
                raise RBACError("Invalid doctor credentials.")
            password_hash = doctor.get("password_hash")
            if password_hash:
                if not self.verify_password(password, password_hash):
                    raise RBACError("Invalid doctor credentials.")
            elif doctor.get("mobile") != password:
                raise RBACError("Invalid doctor credentials.")
            user = self._build_doctor_user(doctor)
            return {"access_token": self.issue_token(user), "user": user}

        if requested_role == Role.NURSE:
            nurse = (
                self._db.get_nurse_by_id(identifier)
                or self._db.get_nurse_by_uhid(identifier)
                or self._db.get_nurse_by_email(identifier.lower())
            )
            if not nurse:
                raise RBACError("Invalid nurse credentials.")
            password_hash = nurse.get("password_hash")
            if password_hash:
                if not self.verify_password(password, password_hash):
                    raise RBACError("Invalid nurse credentials.")
            elif nurse.get("mobile") != password:
                raise RBACError("Invalid nurse credentials.")
            user = self._build_nurse_user(nurse)
            return {"access_token": self.issue_token(user), "user": user}

        raise RBACError("Unsupported role.")

    def change_password(self, current_user: dict, current_password: str, new_password: str) -> None:
        if current_password == new_password:
            raise RBACError("New password must be different from the current password.")
        role = Role(current_user["role"])
        changed_at = datetime.now().isoformat()
        new_hash = self.hash_password(new_password)

        if role == Role.ADMIN:
            raise RBACError("Admin password is configured via environment variables and cannot be changed in-app.")

        if role == Role.PATIENT:
            patient = self._db.get_patient_by_id(current_user["linked_patient_id"])
            if not patient:
                raise RBACError("Patient account not found.")
            stored_hash = patient.get("password_hash")
            if stored_hash:
                if not self.verify_password(current_password, stored_hash):
                    raise RBACError("Current password is incorrect.")
            elif patient.get("mobile") != current_password:
                raise RBACError("Current password is incorrect.")
            if not self._db.update_patient_password(patient["patient_id"], new_hash, changed_at):
                raise RBACError("Unable to update patient password.")
            return

        if role == Role.DOCTOR:
            doctor = self._db.get_doctor_by_id(current_user["linked_doctor_id"])
            if not doctor:
                raise RBACError("Doctor account not found.")
            stored_hash = doctor.get("password_hash")
            if stored_hash:
                if not self.verify_password(current_password, stored_hash):
                    raise RBACError("Current password is incorrect.")
            elif doctor.get("mobile") != current_password:
                raise RBACError("Current password is incorrect.")
            if not self._db.update_doctor_password(doctor["doctor_id"], new_hash, changed_at):
                raise RBACError("Unable to update doctor password.")
            return

        if role == Role.NURSE:
            nurse = self._db.get_nurse_by_id(current_user["linked_nurse_id"])
            if not nurse:
                raise RBACError("Nurse account not found.")
            stored_hash = nurse.get("password_hash")
            if stored_hash:
                if not self.verify_password(current_password, stored_hash):
                    raise RBACError("Current password is incorrect.")
            elif nurse.get("mobile") != current_password:
                raise RBACError("Current password is incorrect.")
            if not self._db.update_nurse_password(nurse["nurse_id"], new_hash, changed_at):
                raise RBACError("Unable to update nurse password.")
            return

        raise RBACError("This role cannot change passwords.")
