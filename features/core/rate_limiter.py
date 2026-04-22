from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _get_user_or_ip(request: Request) -> str:
    """Rate-limit key: JWT user_id when authenticated, client IP otherwise."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        try:
            import jwt as _jwt
            from config import settings
            payload = _jwt.decode(
                auth.split(" ", 1)[1],
                settings.JWT_SECRET,
                algorithms=[settings.JWT_ALGORITHM],
            )
            uid = payload.get("user_id")
            if uid:
                return str(uid)
        except Exception:
            pass
    return get_remote_address(request)


limiter = Limiter(key_func=_get_user_or_ip, default_limits=[])
