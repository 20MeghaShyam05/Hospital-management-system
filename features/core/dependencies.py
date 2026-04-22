from __future__ import annotations

from fastapi import Depends, Header

from features.shared.database.mongo import MongoManager
from features.shared.database.postgres import PostgresManager
from features.shared.services.auth_service import AuthService
from features.shared.services.booking_service import BookingService
from features.shared.services.queue_manager import QueueManager
from features.shared.services.schedule_manager import ScheduleManager
from features.shared.utils.rbac import RBACError, Role


class AppState:
    """Shared service container for the modular monolith."""

    db: PostgresManager
    mongo: MongoManager
    schedule: ScheduleManager
    queue_mgr: QueueManager
    booking: BookingService
    auth: AuthService


app_state = AppState()


def get_booking_service() -> BookingService:
    return app_state.booking


def get_schedule_manager() -> ScheduleManager:
    return app_state.schedule


def get_queue_manager() -> QueueManager:
    return app_state.queue_mgr


def get_db() -> PostgresManager:
    return app_state.db


def get_auth_service() -> AuthService:
    auth = getattr(app_state, "auth", None)
    if auth is None or getattr(auth, "_db", None) is not app_state.db:
        auth = AuthService(db=app_state.db)
        app_state.auth = auth
    return auth


def get_current_user(
    authorization: str | None = Header(default=None),
    auth: AuthService = Depends(get_auth_service),
) -> dict:
    if not authorization:
        return {"user_id": "system", "role": Role.SYSTEM.value, "display_name": "System"}
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise RBACError("Authorization header must use Bearer token.")
    return auth.decode_token(authorization[len(prefix):].strip())


def require_roles(*allowed_roles: Role):
    def dependency(current_user: dict = Depends(get_current_user)) -> dict:
        role = Role(current_user.get("role", Role.SYSTEM.value))
        if role == Role.SYSTEM:
            return current_user
        if role not in allowed_roles:
            raise RBACError(
                f"Role '{role.value}' is not permitted for this operation. "
                f"Required: {[item.value for item in allowed_roles]}"
            )
        return current_user

    return dependency


def ensure_patient_scope(current_user: dict, patient_record: dict) -> None:
    role = Role(current_user.get("role", Role.SYSTEM.value))
    if role in (Role.SYSTEM, Role.ADMIN, Role.FRONT_DESK):
        return
    if role == Role.DOCTOR:
        return
    if role == Role.NURSE:
        return  # Nurses need patient access for triage
    if role == Role.PATIENT and current_user.get("linked_patient_id") == patient_record["patient_id"]:
        return
    raise RBACError("You do not have access to this patient record.")


def ensure_doctor_scope(current_user: dict, doctor_record: dict) -> None:
    role = Role(current_user.get("role", Role.SYSTEM.value))
    if role in (Role.SYSTEM, Role.ADMIN, Role.FRONT_DESK):
        return
    if role == Role.DOCTOR and current_user.get("linked_doctor_id") == doctor_record["doctor_id"]:
        return
    raise RBACError("You do not have access to this doctor scope.")


def ensure_nurse_scope(current_user: dict, nurse_record: dict) -> None:
    role = Role(current_user.get("role", Role.SYSTEM.value))
    if role in (Role.SYSTEM, Role.ADMIN, Role.FRONT_DESK):
        return
    if role == Role.NURSE and current_user.get("linked_nurse_id") == nurse_record["nurse_id"]:
        return
    raise RBACError("You do not have access to this nurse scope.")


def ensure_appointment_scope(current_user: dict, appointment_record: dict) -> None:
    role = Role(current_user.get("role", Role.SYSTEM.value))
    if role in (Role.SYSTEM, Role.ADMIN, Role.FRONT_DESK):
        return
    if role == Role.DOCTOR and current_user.get("linked_doctor_id") == appointment_record["doctor_id"]:
        return
    if role == Role.PATIENT and current_user.get("linked_patient_id") == appointment_record["patient_id"]:
        return
    if role == Role.NURSE:
        return  # Nurses can access appointments for triage
    raise RBACError("You do not have access to this appointment.")
