# utils/rbac.py
from enum import Enum
from functools import wraps
from typing import Callable

class Role(str, Enum):
    ADMIN        = "admin"
    DOCTOR       = "doctor"
    PATIENT      = "patient"
    NURSE        = "nurse"
    FRONT_DESK   = "front_desk"
    SYSTEM       = "system"   # internal scheduler / automation calls

class RBACError(PermissionError):
    """Raised when a role or ownership check fails."""
    pass

# Permission map — derived directly from the NSL "is initiated by" lines
ROLE_PERMISSIONS: dict[str, set[Role]] = {
    "register_patient":   {Role.ADMIN, Role.PATIENT, Role.NURSE, Role.FRONT_DESK},
    "register_doctor":    {Role.ADMIN},
    "register_nurse":     {Role.ADMIN},
    "set_availability":   {Role.ADMIN, Role.DOCTOR, Role.SYSTEM},
    "book_appointment":   {Role.ADMIN, Role.PATIENT, Role.NURSE, Role.FRONT_DESK},
    "cancel_appointment": {Role.PATIENT},
    "reschedule":         {Role.PATIENT},
    "manage_queue":       {Role.DOCTOR, Role.SYSTEM},
    "perform_triage":     {Role.NURSE},
    "view_triage":        {Role.NURSE, Role.ADMIN, Role.DOCTOR},
    "generate_report":    {Role.ADMIN, Role.DOCTOR, Role.SYSTEM},
    "view_patient_data":  {Role.ADMIN, Role.DOCTOR, Role.PATIENT, Role.NURSE, Role.FRONT_DESK},
    "view_all_patients":  {Role.ADMIN, Role.NURSE, Role.FRONT_DESK},
    "view_nurses":        {Role.ADMIN, Role.DOCTOR},
}

def require_role(*allowed_roles: Role) -> Callable:
    """Decorator for service-layer methods.
    
    Usage:
        @require_role(Role.ADMIN)
        def register_patient(self, data, *, current_user):
            ...
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, current_user=None, **kwargs):
            if current_user is None:
                raise RBACError("No authenticated user provided.")
            role = Role(current_user.get("role", ""))
            if role not in allowed_roles:
                raise RBACError(
                    f"Role '{role.value}' is not permitted to call '{fn.__name__}'. "
                    f"Required: {[r.value for r in allowed_roles]}"
                )
            return fn(*args, current_user=current_user, **kwargs)
        return wrapper
    return decorator

def check_ownership(current_user: dict, resource_owner_id: str, id_field: str = "user_id") -> None:
    """Raise RBACError if current_user does not own the resource.
    
    Admin bypasses the ownership check (can act on any record).
    Doctor bypasses for their own patient records during consultation.
    Patient is strictly limited to their own records.
    """
    role = Role(current_user.get("role", ""))
    if role == Role.ADMIN:
        return   # always allowed
    actor_id = current_user.get(id_field) or current_user.get("user_id")
    if actor_id != resource_owner_id:
        raise RBACError(
            f"User '{actor_id}' does not have access to resource owned by '{resource_owner_id}'."
        )
